"""Spec 005 ST19 project classes through the Docker preview's guarded gateway.

Run against the protected Docker preview started by deploy/local/up.py. The suite
starts its own model runner on the host's allowed runner address, adds three
temporary models, enrolls two of them on a fresh managed gateway with the same
installer as ``up.py --runtime-model``, and sends real requests through the
guarded endpoint. Afterwards it puts the gateway and app back on the ordinary
preview configuration and removes what it created. See
project-classes-live-cases.md.
"""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from components.cli import coding, server_connection
from tests.fixtures.class_runner import ClassRunner
from tests.support.client import BASE, RUNTIME, Browser
from tests.support.gateway import GATEWAY_SCRIPT, RESOURCE_PATH
from tests.support.reporting import report_path

REPO = Path(__file__).resolve().parents[2]
REPORT = report_path("project-classes-live.json")
RUNNER_PORT = 14424
RUNNER_ADDRESS = f"http://host.docker.internal:{RUNNER_PORT}"
RUNTIME_PORT = int(os.environ.get("KEEPLANE_RUNTIME_PORT", "5000"))
GUARDED = f"http://127.0.0.1:{RUNTIME_PORT}/v1/chat/completions"
DIRECT = build_opener(ProxyHandler({}))
UNAVAILABLE_START = (
    "{} is approved for this project but can't be used right now, so nothing was sent."
)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment():
    values = dict(
        line.split("=", 1)
        for line in (RUNTIME / ".env").read_text().splitlines()
        if "=" in line
    )
    return {**os.environ, **values}


def compose(*arguments, timeout=180):
    return subprocess.run(
        ["docker", "compose", "--env-file", str(RUNTIME / ".env"), *arguments],
        cwd=REPO,
        env=environment(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def unavailable_reason():
    """Why this environment cannot run the live journey, or None."""
    try:
        with DIRECT.open(BASE + "/health/app", timeout=5) as response:
            if response.status != 200:
                return f"The Keeplane preview at {BASE} did not answer /health/app."
    except (OSError, URLError):
        return (
            f"The Keeplane preview is not reachable at {BASE}. "
            "Start it with `python3 deploy/local/up.py` (docs/guide/local-preview.md)."
        )
    if BASE != "http://127.0.0.1:3000":
        return "These cases enroll the Docker preview's managed gateway; kind is not supported."
    for name in ("first-admin-password", ".env"):
        if not (RUNTIME / name).is_file():
            return f"The preview credential file {RUNTIME / name} is missing."
    try:
        running = compose("ps", "-q", "app", "gateway", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return (
            "Docker Compose is unavailable, so the preview gateway cannot be enrolled."
        )
    if running.returncode or len(running.stdout.split()) != 2:
        return "The Docker preview's app and gateway containers are not both running."
    if listening(RUNTIME_PORT):
        return (
            f"A guarded endpoint already answers on port {RUNTIME_PORT}. These cases "
            "re-enroll the managed gateway and would replace that enrollment."
        )
    if not free(RUNNER_PORT):
        return (
            f"Port {RUNNER_PORT} is in use (for example by the optional Qwen3 runner); "
            "the class fixtures need the preview's allowed runner address."
        )
    return None


def bearer(browser):
    return next(c.value for c in browser.cookies if c.name == "keeplane_session")


def guarded(model, token, project, extra=None):
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "class check"}],
            "max_tokens": 8,
        }
    ).encode()
    headers = {
        "Authorization": "Bearer " + token,
        "X-Keeplane-Project-ID": project,
        "Content-Type": "application/json",
        **(extra or {}),
    }
    try:
        with DIRECT.open(
            Request(GUARDED, data=body, headers=headers), timeout=60
        ) as response:
            raw = response.read(8192)
            status = response.status
    except HTTPError as error:
        raw, status = error.read(8192), error.code
        error.close()
    try:
        answer = json.loads(raw)
    except ValueError:
        answer = {}
    content = None
    if status == 200 and isinstance(answer, dict) and answer.get("choices"):
        content = answer["choices"][0].get("message", {}).get("content")
    return {"status": status, "answer": content}


def run_cases():
    suffix = uuid.uuid4().hex[:8]
    upstream = {
        "conf": "up-conf-" + suffix,
        "spare": "up-spare-" + suffix,
        "public": "up-public-" + suffix,
    }
    names = {
        "conf": "pcl-conf-" + suffix,
        "spare": "pcl-spare-" + suffix,
        "public": "pcl-public-" + suffix,
    }
    approvals = {
        "conf": ["Confidential"],
        "spare": ["Confidential"],
        "public": ["Public"],
    }
    project = str(uuid.uuid4())
    project_name = "Class live " + suffix
    password = (RUNTIME / "first-admin-password").read_text().strip()
    developer_name = "class-live-" + suffix
    developer_password = uuid.uuid4().hex + uuid.uuid4().hex
    cases, created, cleanup_failures = [], [], []
    state = {"mode": None, "developer": None, "enrolled": False, "volume_existed": True}
    admin = Browser()

    def record(identifier, passed, observed):
        cases.append(
            {
                "id": identifier,
                "verdict": "pass" if passed else "fail",
                "observed": observed,
            }
        )

    def set_class(value):
        status, result, _ = admin.fetch(
            f"/api/projects/{project}/class", {"class_id": value}, method="PUT"
        )
        return status, result

    def delta(before, after, key):
        return after[upstream[key]] - before[upstream[key]]

    def cli_choice(model, token):
        try:
            return {
                "model": coding.chosen_model(
                    BASE, project, model, token, lambda _: None
                )
            }
        except server_connection.ConnectionError as error:
            return {"error": str(error), "status": error.status}

    def cli_catalog(token):
        return [
            row["id"]
            for row in server_connection.models(BASE, project, token)["models"]
        ]

    with ClassRunner(upstream.values(), port=RUNNER_PORT) as runner:
        try:
            assert admin.login("first-admin", password)[0] == 200
            state["mode"] = admin.fetch("/api/data-classes")[1]["enabled"]
            assert (
                admin.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")[
                    0
                ]
                == 200
            )
            for key in ("conf", "spare", "public"):
                status, result, _ = admin.fetch(
                    "/api/models",
                    {
                        "name": names[key],
                        "model": upstream[key],
                        "source": "runner",
                        "address": RUNNER_ADDRESS,
                        "approved_classes": approvals[key],
                    },
                    method="POST",
                )
                if status != 200:
                    raise RuntimeError(
                        f"Adding fixture model {key} returned {status}: {result}"
                    )
                created.append(names[key])

            volume = "keeplane-local_runtime-installation"
            state["volume_existed"] = (
                subprocess.run(
                    ["docker", "volume", "inspect", volume],
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            )
            launcher = load("keeplane_up", REPO / "deploy/local/up.py")
            launcher.RUNTIME = RUNTIME
            guard = load(
                "keeplane_guarded_runtime", REPO / "deploy/local/guarded_runtime.py"
            )
            state["enrolled"] = True
            guard.install(
                REPO,
                RUNTIME,
                [names["conf"], names["public"]],
                RUNTIME_PORT,
                env=environment(),
                wait_ready=lambda: launcher.wait_preview(BASE),
            )
            admin = Browser()
            assert admin.login("first-admin", password)[0] == 200
            admin_token = bearer(admin)

            status, user, _ = admin.fetch(
                "/api/users",
                {
                    "username": developer_name,
                    "role": "developer",
                    "password": developer_password,
                },
                method="POST",
            )
            if status != 201:
                raise RuntimeError(f"Creating the developer returned {status}")
            state["developer"] = user["id"]
            developer = Browser()
            assert developer.login(developer_name, developer_password)[0] == 200
            token = bearer(developer)
            status, _, _ = developer.fetch(
                "/api/runtime/projects",
                {"project_id": project, "name": project_name},
                method="POST",
                csrf=False,
                headers={"Authorization": "Bearer " + token},
            )
            if status != 200:
                raise RuntimeError(f"Registering the project returned {status}")

            # PCL-LIVE-01: Set a class.
            put_status, _ = set_class("confidential")
            _, listing, _ = admin.fetch("/api/projects?search=" + suffix)
            row = next(
                (item for item in listing["projects"] if item["id"] == project), {}
            )
            _, current, _ = admin.fetch(f"/api/projects/{project}/class")
            record(
                "PCL-LIVE-01",
                put_status == 200
                and row.get("data_class", {}).get("id") == "confidential"
                and current.get("data_class", {}).get("id") == "confidential",
                {
                    "write_status": put_status,
                    "listed_class": row.get("data_class"),
                    "read_back": current.get("data_class"),
                },
            )

            # PCL-LIVE-02: Only approved models.
            before = runner.snapshot()
            allowed = guarded(names["conf"], token, project)
            after = runner.snapshot()
            catalog = cli_catalog(token)
            record(
                "PCL-LIVE-02",
                allowed["status"] == 200
                and allowed["answer"] == "class answer"
                and delta(before, after, "conf") == 1
                and delta(before, after, "public") == 0
                and names["public"] not in catalog
                and names["conf"] in catalog,
                {
                    "gateway_status": allowed["status"],
                    "upstream_calls": {k: delta(before, after, k) for k in upstream},
                    "catalog": catalog,
                },
            )

            # PCL-LIVE-03: A model for another class, named directly.
            before = runner.snapshot()
            forged = {
                "X-Keeplane-Class": "Public",
                "X-Keeplane-Actor-ID": "someone-else",
                "X-Keeplane-Installed-Runtime": "operator",
            }
            attempts = {
                "developer": guarded(names["public"], token, project)["status"],
                "developer_forged_headers": guarded(
                    names["public"], token, project, forged
                )["status"],
                "admin": guarded(names["public"], admin_token, project)["status"],
            }
            choice = cli_choice(names["public"], token)
            after = runner.snapshot()
            record(
                "PCL-LIVE-03",
                all(status == 403 for status in attempts.values())
                and choice.get("status") == 403
                and sum(delta(before, after, k) for k in upstream) == 0,
                {
                    "gateway_status": attempts,
                    "cli_model_choice": choice,
                    "upstream_calls": {k: delta(before, after, k) for k in upstream},
                },
            )

            # PCL-LIVE-04: The repository's own settings name another model.
            before = runner.snapshot()
            repository_setting = names["public"]
            provider_name = upstream["public"]
            catalog = cli_catalog(token)
            choice = cli_choice(repository_setting, token)
            sent = guarded(repository_setting, token, project)["status"]
            raw_name = guarded(provider_name, token, project)["status"]
            after = runner.snapshot()
            record(
                "PCL-LIVE-04",
                repository_setting not in catalog
                and choice.get("status") == 403
                and sent == 403
                and not 200 <= raw_name < 300
                and sum(delta(before, after, k) for k in upstream) == 0,
                {
                    "in_cli_catalog": repository_setting in catalog,
                    "cli_model_choice": choice,
                    "gateway_status": {
                        "keeplane_name": sent,
                        "provider_model_name": raw_name,
                    },
                    "upstream_calls": {k: delta(before, after, k) for k in upstream},
                },
            )

            # PCL-LIVE-05: No class.
            clear_status, cleared = set_class(None)
            before = runner.snapshot()
            catalog = cli_catalog(token)
            public = guarded(names["public"], token, project)
            conf = guarded(names["conf"], token, project)
            choice = cli_choice(names["public"], token)
            after = runner.snapshot()
            record(
                "PCL-LIVE-05",
                clear_status == 200
                and cleared.get("data_class") is None
                and {names["conf"], names["spare"], names["public"]} <= set(catalog)
                and choice.get("model") == names["public"]
                and public["status"] == 200
                and conf["status"] == 200
                and delta(before, after, "public") == 1
                and delta(before, after, "conf") == 1,
                {
                    "clear_status": clear_status,
                    "catalog": catalog,
                    "cli_model_choice": choice,
                    "gateway_status": {
                        "public": public["status"],
                        "confidential": conf["status"],
                    },
                    "upstream_calls": {k: delta(before, after, k) for k in upstream},
                },
            )

            # PCL-LIVE-06: No approved model is up. The enrolled Confidential
            # model's provider fails; the other Confidential model is set up
            # but not enrolled on the guarded gateway.
            reset_status, _ = set_class("confidential")
            runner.set_down({upstream["conf"]})
            before = runner.snapshot()
            spare_choice = cli_choice(names["spare"], token)
            spare = guarded(names["spare"], token, project)["status"]
            failing = guarded(names["conf"], token, project)["status"]
            other = guarded(names["public"], token, project)["status"]
            after = runner.snapshot()
            runner.set_down(set())
            record(
                "PCL-LIVE-06",
                reset_status == 200
                and spare_choice.get("status") == 503
                and spare_choice.get("error", "").startswith(
                    UNAVAILABLE_START.format(names["spare"])
                )
                and not 200 <= spare < 300
                and failing >= 500
                and other == 403
                and delta(before, after, "conf") >= 1
                and delta(before, after, "spare") == 0
                and delta(before, after, "public") == 0,
                {
                    "cli_model_choice": spare_choice,
                    "gateway_status": {
                        "not_enrolled_confidential": spare,
                        "failing_confidential": failing,
                        "public": other,
                    },
                    "upstream_calls": {k: delta(before, after, k) for k in upstream},
                },
            )
        finally:
            restore(admin, password, project, created, state, cleanup_failures)
    cleanup = "complete" if not cleanup_failures else "; ".join(cleanup_failures)
    report = {
        "suite": "Spec 005 ST19 project classes through the guarded Docker preview gateway",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
        "cleanup": cleanup,
        "passed": sum(case["verdict"] == "pass" for case in cases),
        "failed": sum(case["verdict"] == "fail" for case in cases),
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{report['passed']} passed, {report['failed']} failed; cleanup {cleanup}; {REPORT}"
    )
    for case in cases:
        print(case["id"], case["verdict"], json.dumps(case["observed"]))
    return int(bool(report["failed"]) or cleanup != "complete")


def restore(admin, password, project, created, state, failures):
    """Return the preview to its ordinary gateway and remove this run's records."""
    if state["enrolled"]:
        result = compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--no-deps",
            "--force-recreate",
            "gateway",
            "app",
        )
        if result.returncode:
            failures.append("ordinary gateway and app were not recreated")
        else:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    with DIRECT.open(BASE + "/health/app", timeout=3) as response:
                        if response.status == 200:
                            break
                except (OSError, URLError):
                    pass
                time.sleep(1)
        if not state["volume_existed"]:
            subprocess.run(
                ["docker", "volume", "rm", "keeplane-local_runtime-installation"],
                capture_output=True,
                check=False,
                timeout=60,
            )
        if listening(RUNTIME_PORT):
            failures.append(f"guarded port {RUNTIME_PORT} still answers")
    try:
        admin = Browser()
        if admin.login("first-admin", password)[0] != 200:
            raise RuntimeError("sign-in failed")
        admin.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")
        status, _, _ = admin.fetch(
            f"/api/projects/{project}/class", {"class_id": None}, method="PUT"
        )
        if status not in (200, 404):
            failures.append(f"project class clear returned {status}")
        for name in created:
            status, _, _ = admin.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
            if status not in (200, 404):
                failures.append(f"{name} setup removal returned {status}")
            removed = compose(
                "exec",
                "-T",
                "app",
                "python",
                "-c",
                GATEWAY_SCRIPT,
                "DELETE",
                RESOURCE_PATH + "/" + name,
                "-",
                timeout=60,
            )
            if removed.returncode:
                failures.append(f"{name} gateway removal could not be confirmed")
        if state["developer"]:
            status, _, _ = admin.fetch(
                f"/api/users/{state['developer']}", {}, method="DELETE"
            )
            if status != 200:
                failures.append(f"developer removal returned {status}")
        if state["mode"] is not None:
            status, _, _ = admin.fetch(
                "/api/data-classes/mode", {"enabled": state["mode"]}, method="PUT"
            )
            if status != 200:
                failures.append(f"mode restore returned {status}")
        admin.fetch("/sign-out", method="POST")
    except Exception as error:  # Report, never hide, an incomplete restore.
        failures.append(f"restore raised {type(error).__name__}")


if __name__ == "__main__":
    reason = unavailable_reason()
    if reason:
        print("Not run: " + reason)
        sys.exit(2)
    sys.exit(run_cases())


def test_project_classes_live(capsys):
    reason = unavailable_reason()
    if reason:
        pytest.skip(reason)
    assert run_cases() == 0
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, REPORT)


pytestmark = pytest.mark.docker_only
