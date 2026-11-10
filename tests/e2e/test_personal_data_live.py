"""Spec 005 ST20 and Spec 006 ST21 personal-data detection through the live gateway.

Run against the protected Docker preview started by deploy/local/up.py, with an
app image built from the `detection` target (KEEPLANE_PREVIEW_DETECTION_IMAGE,
by default keeplane-preview:detection-local). The suite starts its own model
runner, adds four temporary models, enrols them on a fresh managed gateway
with the preview's own installer and KEEPLANE_PERSONAL_DATA_DETECTION=1, turns
detection on and sends real requests from the fixed English set through the
guarded endpoint. Afterwards it puts the preview back as it found it, like the
project classes suite. See personal-data-live-cases.md.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from tests.e2e import test_project_classes_live as classes
from tests.fixtures.class_runner import ClassRunner
from tests.support.client import BASE, RUNTIME, Browser
from tests.support.reporting import report_path

REPO = classes.REPO
REPORT = report_path("personal-data-live.json")
IMAGE = os.environ.get(
    "KEEPLANE_PREVIEW_DETECTION_IMAGE", "keeplane-preview:detection-local"
)
SET = REPO / "tests/fixtures/personal_data/english-set.json"
# From the fixed English set: one email, one phone and one card request, and
# three clean code-shaped requests. The detector misses none of these kinds
# and holds none of these forms on this set (PM-03 and PM-04, which CI runs in
# the detection image).
PERSONAL = ("EN2-027", "EN2-045", "EN2-061")
CLEAN = ("EN2-146", "EN2-151", "EN2-155")
HELD_CLASS = "Confidential"
REASON = {
    "found": "Personal data detected",
    "long": "Detection took longer than 200 ms",
    "down": "Detection was down",
}
RECORD = re.compile(
    r"Request (?P<reference>HR-[0-9a-f]{12}) in (?P<project>.+) held back "
    r"(?P<how>by detection|because detection couldn't check it), "
    r"handled as (?P<held_as>\w+) \((?P<why>[^)]+)\); "
    r"(?:approved model (?P<approved>\S+)"
    r"|model (?P<refused>\S+) isn't approved for it, nothing was sent)"
)
# Over the detector's 100 000-character limit, under the gateway's 1 MiB.
LONG_REPEAT = 1200


def detection_unavailable_reason():
    reason = classes.unavailable_reason()
    if reason:
        return reason
    found = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if found.returncode:
        return (
            f"The detection app image {IMAGE} is not built. Build it with "
            "`docker build -f components/control-plane/Dockerfile --target detection "
            f"-t {IMAGE} .`"
        )
    return None


def detection_environment():
    """Compose settings for the guarded preview with detection installed."""
    return {
        **classes.environment(),
        "KEEPLANE_RUNTIME_APP_IMAGE": IMAGE,
        "KEEPLANE_PERSONAL_DATA_DETECTION": "1",
        "KEEPLANE_RUNTIME_PORT": str(classes.RUNTIME_PORT),
    }


def recreate_app(override=None):
    """Recreate the guarded app with the detection image, optionally overridden."""
    files = [
        "-f", str(REPO / "compose.yaml"),
        "-f", str(REPO / "deploy/local/runtime.yaml"),
    ]
    if override:
        files += ["-f", str(override)]
    result = subprocess.run(
        [
            "docker", "compose", "--env-file", str(RUNTIME / ".env"), *files,
            "up", "-d", "--no-build", "--pull", "never", "--no-deps",
            "--force-recreate", "app",
        ],
        cwd=REPO,
        env=detection_environment(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("The guarded app was not recreated: " + result.stderr[-400:])
    wait_ready()


def wait_ready(timeout=330):
    """Wait until the app is ready, which includes its detector's first load."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with classes.DIRECT.open(BASE + "/health/app", timeout=3) as response:
                if response.status == 200:
                    break
        except (OSError, URLError):
            pass
        time.sleep(2)
    else:
        raise RuntimeError("The app did not become ready")
    launcher = classes.load("keeplane_up", REPO / "deploy/local/up.py")
    launcher.RUNTIME = RUNTIME
    launcher.wait_preview(BASE)


def send(model, token, project, text):
    """One chat request through the guarded endpoint; status and what came back."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": text}],
            "max_tokens": 8,
        }
    ).encode()
    headers = {
        "Authorization": "Bearer " + token,
        "X-Keeplane-Project-ID": project,
        "Content-Type": "application/json",
    }
    try:
        with classes.DIRECT.open(
            Request(classes.GUARDED, data=body, headers=headers), timeout=60
        ) as response:
            raw, status = response.read(8192), response.status
    except HTTPError as error:
        raw, status = error.read(8192), error.code
        error.close()
    text_answer = raw.decode("utf-8", "replace")
    try:
        answer = json.loads(raw)
    except ValueError:
        answer = {}
    error = answer.get("error") if isinstance(answer, dict) else None
    if isinstance(error, dict):
        error = error.get("message")
    content = None
    if status == 200 and isinstance(answer, dict) and answer.get("choices"):
        content = answer["choices"][0].get("message", {}).get("content")
    return {"status": status, "answer": content, "error": error, "body": text_answer}


def held_message(model):
    return (
        f"This request is handled as {HELD_CLASS} and {model} isn't approved for "
        "it, so nothing was sent. Run it with a model approved for "
        f"{HELD_CLASS}, or ask your admin to approve one."
    )


def run_cases():
    fixed = {
        case["id"]: case
        for case in json.loads(SET.read_text(encoding="utf-8"))["cases"]
    }
    personal = [fixed[identifier] for identifier in PERSONAL]
    clean = [fixed[identifier] for identifier in CLEAN]
    assert all(case["kind"] == "positive" for case in personal)
    assert {item["type"] for case in personal for item in case["expect"]} == {
        "EMAIL", "PHONE", "CARD",
    }
    assert all(case["kind"] == "clean" for case in clean)
    secrets_in_text = [item["value"] for case in personal for item in case["expect"]]
    long_text = (clean[0]["text"] + "\n\n") * LONG_REPEAT
    assert 100_000 < len(long_text) < 1024 * 1024

    suffix = uuid.uuid4().hex[:8]
    keys = ("public", "conf", "internal", "both")
    upstream = {key: f"up-{key}-{suffix}" for key in keys}
    names = {key: f"pdl-{key}-{suffix}" for key in keys}
    approvals = {
        "public": ["Public"],
        "conf": ["Confidential"],
        "internal": ["Internal"],
        "both": ["Internal", "Confidential"],
    }
    project = str(uuid.uuid4())
    second = str(uuid.uuid4())
    project_names = {project: "Detection live " + suffix, second: "Detection internal " + suffix}
    password = (RUNTIME / "first-admin-password").read_text().strip()
    developer_name = "detection-live-" + suffix
    developer_password = uuid.uuid4().hex + uuid.uuid4().hex
    cases, created, cleanup_failures = [], [], []
    state = {
        "mode": None,
        "developer": None,
        "enrolled": False,
        "settled": False,
        "detection": None,
        "audit": None,
    }
    sent_texts = []
    admin = Browser()

    def record(identifier, passed, observed):
        cases.append(
            {"id": identifier, "verdict": "pass" if passed else "fail", "observed": observed}
        )

    def sign_in():
        nonlocal admin
        admin = Browser()
        if admin.login("first-admin", password)[0] != 200:
            raise RuntimeError("The admin could not sign in")

    def detection(enabled, class_id="confidential"):
        status, result, _ = admin.fetch(
            "/api/data-classes/detection",
            {"enabled": enabled, "class_id": class_id},
            method="PUT",
        )
        return status, result

    def audit_switch(enabled):
        status, _, _ = admin.fetch(
            "/api/audit/options/held_requests", {"enabled": enabled}, method="PUT"
        )
        return status

    def held_records():
        rows, page = {}, 1
        while True:
            status, result, _ = admin.fetch(
                f"/api/audit/records?kind=held_requests&search={suffix}&page={page}"
            )
            if status != 200:
                raise RuntimeError(f"Reading Audit returned {status}")
            for row in result["records"]:
                rows[row["id"]] = row
            if page * 25 >= result["total"]:
                return rows
            page += 1

    def request(key, text, project_id=project):
        sent_texts.append(text)
        return send(names[key], token, project_id, text)

    def check_records(rows, expected):
        """Rows match the expected (model key, allowed, reason, project) holds."""
        found, problems = [], []
        for row in rows:
            match = RECORD.fullmatch(row["what"])
            if not match:
                problems.append("unreadable record")
                continue
            held_as, why, project_name = match.group("held_as", "why", "project")
            approved, refused = match.group("approved", "refused")
            # A finding reads "by detection"; any other reason, that
            # detection couldn't check the request.
            expected_how = (
                "by detection"
                if why == "Personal data detected"
                else "because detection couldn't check it"
            )
            if match.group("how") != expected_how:
                problems.append("wrong hold wording for its reason")
            found.append(
                (approved or refused, approved is not None, why, project_name)
            )
            if row["who"] != developer_name or held_as != HELD_CLASS:
                problems.append("wrong developer or class")
            try:
                datetime.fromisoformat(row["when"])
            except (TypeError, ValueError):
                problems.append("no time")
            if any(text in row["what"] for text in sent_texts) or any(
                value in row["what"] for value in secrets_in_text
            ):
                problems.append("request text in a record")
        references = [
            match.group("reference")
            for match in (RECORD.fullmatch(row["what"]) for row in rows)
            if match
        ]
        if len(set(references)) != len(references):
            problems.append("a reference was reused")
        wanted = sorted(
            (names[key], allowed, REASON[why], project_names[project_id])
            for key, allowed, why, project_id in expected
        )
        return sorted(found) == wanted and not problems, {
            "records": sorted(found),
            "problems": problems,
        }

    def new_since(before):
        return [row for key, row in sorted(held_records().items()) if key not in before]

    with ClassRunner(upstream.values(), port=classes.RUNNER_PORT) as runner:

        def delta(before, after):
            return {key: after[upstream[key]] - before[upstream[key]] for key in keys}

        try:
            sign_in()
            listing = admin.fetch("/api/data-classes")[1]
            state["mode"] = listing["enabled"]
            if admin.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")[0] != 200:
                raise RuntimeError("Data classes could not be turned on")
            state["detection"] = admin.fetch("/api/data-classes")[1]["detection"]
            state["audit"] = admin.fetch("/api/audit/options")[1]["options"]["held_requests"]
            for key in keys:
                status, result, _ = admin.fetch(
                    "/api/models",
                    {
                        "name": names[key],
                        "model": upstream[key],
                        "source": "runner",
                        "address": classes.RUNNER_ADDRESS,
                        "approved_classes": approvals[key],
                    },
                    method="POST",
                )
                if status != 200:
                    raise RuntimeError(f"Adding fixture model {key} returned {status}: {result}")
                created.append(names[key])

            guard = classes.load(
                "keeplane_guarded_runtime", REPO / "deploy/local/guarded_runtime.py"
            )
            state["enrolled"] = True
            guard.install(
                REPO,
                RUNTIME,
                [names[key] for key in keys],
                classes.RUNTIME_PORT,
                env=detection_environment(),
                wait_ready=wait_ready,
            )
            state["settled"] = classes.enroller_settled(len(keys))
            if not state["settled"]:
                raise RuntimeError("The model enroller did not settle after enrolment")
            sign_in()

            status, user, _ = admin.fetch(
                "/api/users",
                {"username": developer_name, "role": "developer", "password": developer_password},
                method="POST",
            )
            if status != 201:
                raise RuntimeError(f"Creating the developer returned {status}")
            state["developer"] = user["id"]
            developer = Browser()
            assert developer.login(developer_name, developer_password)[0] == 200
            token = classes.bearer(developer)
            for project_id, name in project_names.items():
                status, _, _ = developer.fetch(
                    "/api/runtime/projects",
                    {"project_id": project_id, "name": name},
                    method="POST",
                    csrf=False,
                    headers={"Authorization": "Bearer " + token},
                )
                if status != 200:
                    raise RuntimeError(f"Registering a project returned {status}")
            if admin.fetch(f"/api/projects/{second}/class", {"class_id": "internal"}, method="PUT")[0] != 200:
                raise RuntimeError("The second project's class could not be set")
            if audit_switch(True) != 200:
                raise RuntimeError("The held-back requests switch could not be turned on")

            # PDL-LIVE-01: Detection off changes nothing.
            off_status, _ = detection(False)
            records = held_records()
            before = runner.snapshot()
            answers = [request("public", case["text"]) for case in personal + clean]
            after = runner.snapshot()
            fresh = new_since(records)
            record(
                "PDL-LIVE-01",
                off_status == 200
                and all(a["status"] == 200 and a["answer"] == "class answer" for a in answers)
                and delta(before, after) == {"public": 6, "conf": 0, "internal": 0, "both": 0}
                and fresh == [],
                {
                    "detection_write": off_status,
                    "gateway_status": [a["status"] for a in answers],
                    "upstream_calls": delta(before, after),
                    "held_records": len(fresh),
                },
            )

            # PDL-LIVE-02: Personal data is held to Confidential.
            on_status, _ = detection(True)
            listed = admin.fetch("/api/data-classes")[1]["detection"]
            records = held_records()
            before = runner.snapshot()
            refused, allowed = [], []
            for case in personal:
                refused.append(request("public", case["text"]))
                allowed.append(request("conf", case["text"]))
            after = runner.snapshot()
            ok, seen = check_records(
                new_since(records),
                [("public", False, "found", project), ("conf", True, "found", project)] * 3,
            )
            record(
                "PDL-LIVE-02",
                on_status == 200
                and listed == {"enabled": True, "class_id": "confidential", "available": True}
                and all(r["status"] == 403 and r["error"] == held_message(names["public"]) for r in refused)
                and all(a["status"] == 200 and a["answer"] == "class answer" for a in allowed)
                and delta(before, after) == {"public": 0, "conf": 3, "internal": 0, "both": 0}
                and ok,
                {
                    "detection": listed,
                    "public_model": [(r["status"], r["error"]) for r in refused],
                    "confidential_model": [a["status"] for a in allowed],
                    "upstream_calls": delta(before, after),
                    "held_records": seen,
                },
            )

            # PDL-LIVE-03: A clean request routes unchanged.
            records = held_records()
            before = runner.snapshot()
            answers = [request("public", case["text"]) for case in clean]
            after = runner.snapshot()
            fresh = new_since(records)
            record(
                "PDL-LIVE-03",
                all(a["status"] == 200 and a["answer"] == "class answer" for a in answers)
                and delta(before, after) == {"public": 3, "conf": 0, "internal": 0, "both": 0}
                and fresh == [],
                {
                    "gateway_status": [a["status"] for a in answers],
                    "upstream_calls": delta(before, after),
                    "held_records": [row["what"] for row in fresh],
                },
            )

            # PDL-LIVE-04: The project's own class still applies.
            records = held_records()
            before = runner.snapshot()
            text = personal[0]["text"]
            held = {
                key: request(key, text, second) for key in ("conf", "internal", "both")
            }
            clean_internal = request("internal", clean[0]["text"], second)
            clean_conf = request("conf", clean[0]["text"], second)
            after = runner.snapshot()
            ok, seen = check_records(
                new_since(records),
                [
                    ("conf", False, "found", second),
                    ("internal", False, "found", second),
                    ("both", True, "found", second),
                ],
            )
            record(
                "PDL-LIVE-04",
                held["conf"]["status"] == 403
                and held["conf"]["error"] == held_message(names["conf"])
                and held["internal"]["status"] == 403
                and held["internal"]["error"] == held_message(names["internal"])
                and held["both"]["status"] == 200
                and clean_internal["status"] == 200
                and clean_conf["status"] == 403
                and clean_conf["error"] != held_message(names["conf"])
                and delta(before, after) == {"public": 0, "conf": 0, "internal": 1, "both": 1}
                and ok,
                {
                    "personal_data": {k: (v["status"], v["error"]) for k, v in held.items()},
                    "clean": {
                        "internal": clean_internal["status"],
                        "confidential": (clean_conf["status"], clean_conf["error"]),
                    },
                    "upstream_calls": delta(before, after),
                    "held_records": seen,
                },
            )

            # PDL-LIVE-05: A request too long to check in time is held.
            records = held_records()
            before = runner.snapshot()
            long_public = request("public", long_text)
            long_conf = request("conf", long_text)
            after = runner.snapshot()
            ok, seen = check_records(
                new_since(records),
                [("public", False, "long", project), ("conf", True, "long", project)],
            )
            record(
                "PDL-LIVE-05",
                long_public["status"] == 403
                and long_public["error"] == held_message(names["public"])
                and long_conf["status"] == 200
                and delta(before, after) == {"public": 0, "conf": 1, "internal": 0, "both": 0}
                and ok,
                {
                    "characters": len(long_text),
                    "gateway_status": {
                        "public": (long_public["status"], long_public["error"]),
                        "confidential": long_conf["status"],
                    },
                    "upstream_calls": delta(before, after),
                    "held_records": seen,
                },
            )

            # PDL-LIVE-06: Detection is down.
            with tempfile.TemporaryDirectory() as folder:
                override = Path(folder) / "detection-down.yaml"
                override.write_text(
                    "services:\n  app:\n    environment:\n"
                    "      KEEPLANE_PERSONAL_DATA_MODEL: en_core_web_absent\n"
                )
                recreate_app(override)
            sign_in()
            down_setting = admin.fetch("/api/data-classes")[1]["detection"]
            records = held_records()
            before = runner.snapshot()
            down_public = request("public", clean[1]["text"])
            down_conf = request("conf", clean[1]["text"])
            after = runner.snapshot()
            attempts = delta(before, after)["conf"]
            ok, seen = check_records(
                new_since(records),
                [("public", False, "down", project)]
                + [("conf", True, "down", project)] * (1 + attempts),
            )
            recreate_app()
            sign_in()
            back = admin.fetch("/api/data-classes")[1]["detection"]
            record(
                "PDL-LIVE-06",
                down_setting == {"enabled": True, "class_id": "confidential", "available": False}
                and down_public["status"] == 403
                and down_public["error"] == held_message(names["public"])
                and down_conf["status"] == 200
                and delta(before, after) == {"public": 0, "conf": 1, "internal": 0, "both": 0}
                and ok
                and back["available"] is True,
                {
                    "detection_while_down": down_setting,
                    "gateway_status": {
                        "public": (down_public["status"], down_public["error"]),
                        "confidential": down_conf["status"],
                    },
                    "upstream_calls": delta(before, after),
                    "held_records": seen,
                    "detection_after_restart": back,
                },
            )

            # PDL-LIVE-07: Held-back requests not recorded while the switch is off.
            switch_status = audit_switch(False)
            records = held_records()
            before = runner.snapshot()
            quiet_public = request("public", personal[1]["text"])
            quiet_conf = request("conf", personal[1]["text"])
            after = runner.snapshot()
            fresh = new_since(records)
            record(
                "PDL-LIVE-07",
                switch_status == 200
                and quiet_public["status"] == 403
                and quiet_public["error"] == held_message(names["public"])
                and quiet_conf["status"] == 200
                and delta(before, after) == {"public": 0, "conf": 1, "internal": 0, "both": 0}
                and fresh == [],
                {
                    "switch_write": switch_status,
                    "gateway_status": {
                        "public": (quiet_public["status"], quiet_public["error"]),
                        "confidential": quiet_conf["status"],
                    },
                    "upstream_calls": delta(before, after),
                    "held_records": len(fresh),
                },
            )

            # PDL-LIVE-08: Turning detection off again changes no route.
            switch_status = audit_switch(True)
            off_status, _ = detection(False)
            records = held_records()
            before = runner.snapshot()
            answers = [request("public", personal[2]["text"]), request("public", long_text)]
            after = runner.snapshot()
            fresh = new_since(records)
            record(
                "PDL-LIVE-08",
                switch_status == 200
                and off_status == 200
                and all(a["status"] == 200 for a in answers)
                and delta(before, after) == {"public": 2, "conf": 0, "internal": 0, "both": 0}
                and fresh == [],
                {
                    "detection_write": off_status,
                    "gateway_status": [a["status"] for a in answers],
                    "upstream_calls": delta(before, after),
                    "held_records": len(fresh),
                },
            )
        finally:
            if state["enrolled"] and (
                not state["settled"] or any(c["verdict"] != "pass" for c in cases)
            ):
                classes.enroller_diagnostics(list(names.values()))
            restore_detection(admin, password, second, state, cleanup_failures)
            classes.restore(admin, password, project, created, state, cleanup_failures)
    cleanup = "complete" if not cleanup_failures else "; ".join(cleanup_failures)
    report = {
        "suite": "Spec 005 ST20 and Spec 006 ST21 personal-data detection through the guarded Docker preview gateway",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
        "cleanup": cleanup,
        "passed": sum(case["verdict"] == "pass" for case in cases),
        "failed": sum(case["verdict"] == "fail" for case in cases),
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['passed']} passed, {report['failed']} failed; cleanup {cleanup}; {REPORT}")
    for case in cases:
        print(case["id"], case["verdict"], json.dumps(case["observed"]))
    return int(bool(report["failed"]) or cleanup != "complete")


def restore_detection(admin, password, second, state, failures):
    """Put detection, the Audit switch and the second project back first."""
    try:
        admin = Browser()
        if admin.login("first-admin", password)[0] != 200:
            raise RuntimeError("sign-in failed")
        admin.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")
        if state["detection"] is not None:
            previous = state["detection"]
            status, _, _ = admin.fetch(
                "/api/data-classes/detection",
                {"enabled": previous["enabled"], "class_id": previous["class_id"]},
                method="PUT",
            )
            if status != 200:
                failures.append(f"detection restore returned {status}")
        if state["audit"] is not None:
            status, _, _ = admin.fetch(
                "/api/audit/options/held_requests",
                {"enabled": state["audit"]},
                method="PUT",
            )
            if status != 200:
                failures.append(f"Audit switch restore returned {status}")
        status, _, _ = admin.fetch(
            f"/api/projects/{second}/class", {"class_id": None}, method="PUT"
        )
        if status not in (200, 404):
            failures.append(f"second project class clear returned {status}")
        admin.fetch("/sign-out", method="POST")
    except Exception as error:  # Report, never hide, an incomplete restore.
        failures.append(f"detection restore raised {type(error).__name__}")


if __name__ == "__main__":
    reason = detection_unavailable_reason()
    if reason:
        print("Not run: " + reason)
        sys.exit(2)
    sys.exit(run_cases())


def test_personal_data_live(capsys):
    reason = detection_unavailable_reason()
    if reason:
        pytest.skip(reason)
    assert run_cases() == 0
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, REPORT)


pytestmark = pytest.mark.docker_only
