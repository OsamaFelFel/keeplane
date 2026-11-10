"""Spec 004 ST23 and ST24: model setup reaches the running guarded gateway.

Run against the Docker preview started by ``python3 deploy/local/up.py``
(task 004-01, ADR 027). The suite puts a model straight into the managed
gateway, as an operator would outside Keeplane, and checks it gets no work
until an admin sets it up with data classes off. Then it changes the model's
destination in the gateway, sets it up again and removes its setup. Each time
it checks the model enroller's report and real requests through the guarded
port, and that the gateway was never restarted. See
model-setup-live-cases.md.
"""

import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

import pytest

from tests.e2e import test_preview_sign_in_live as preview
from tests.e2e import test_project_classes_live as classes
from tests.fixtures.class_runner import ClassRunner
from tests.support.client import RUNTIME, Browser
from tests.support.gateway import RESOURCE_PATH, gateway_call
from tests.support.reporting import report_path

pytestmark = [pytest.mark.live, pytest.mark.docker_only]

REPORT = report_path("model-setup-live.json")
CASES = tuple(f"MSL-LIVE-0{number}" for number in range(1, 6))
HELD = "A model change is waiting"
# An edit or removal of a served model holds the enroller for about 3 minutes
# and 16 seconds (ADR 027); allow for a pass under way on either side.
HOLD_TIMEOUT = 330


def outside_definition(name, upstream):
    """A gateway model the way an operator writes it, outside Keeplane."""
    return {
        "id": name,
        "name": name,
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {"model": upstream, "baseUrl": classes.RUNNER_ADDRESS + "/v1"},
    }


def put_outside(name, upstream):
    status, _ = gateway_call(
        "PUT",
        RESOURCE_PATH,
        {"resources": [{"value": outside_definition(name, upstream)}]},
    )
    return status


def gateway_started():
    """When the managed gateway container last started, or None."""
    listed = classes.compose("ps", "-q", "gateway", timeout=30)
    ids = listed.stdout.split()
    if listed.returncode or len(ids) != 1:
        return None
    inspected = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.StartedAt}}", ids[0]],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return inspected.stdout.strip() or None


def reports_since(mark):
    return preview.enroller_reports()[mark:]


def wait_after(mark, expected, timeout):
    """Wait for a report after ``mark`` and until the latest is in ``expected``.

    Returns every report seen after ``mark``, or None on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        seen = reports_since(mark)
        if seen and seen[-1] in expected:
            return seen
        time.sleep(1)
    return None


def run_cases():
    suffix = uuid.uuid4().hex[:8]
    name = "msl-" + suffix
    first, second = "msl-first-" + suffix, "msl-second-" + suffix
    project = str(uuid.uuid4())
    password = (RUNTIME / "first-admin-password").read_text().strip()
    developer_name = "setup-live-" + suffix
    developer_password = uuid.uuid4().hex + uuid.uuid4().hex
    cases, failures = [], []
    state = {"mode": None, "developer": None, "gateway": False, "setup": False}
    approved_before = []
    admin = Browser()

    def record(identifier, passed, observed):
        cases.append(
            {
                "id": identifier,
                "verdict": "pass" if passed else "fail",
                "observed": observed,
            }
        )

    def listed():
        """The model's row in Models and routing, or None."""
        _, listing, _ = admin.fetch("/api/models")
        return next(
            (row for row in listing.get("models", []) if row["id"] == name), None
        )

    def wait_listed(timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = listed()
            if row is not None:
                return row
            time.sleep(1)
        return None

    with ClassRunner([first, second], port=classes.RUNNER_PORT) as runner:

        def calls():
            snapshot = runner.snapshot()
            return {key: snapshot.get(key, 0) for key in (first, second)}

        def sent(token):
            """One guarded request and what reached the runner meanwhile."""
            before = calls()
            answer = preview.guarded(token, project, name)
            after = calls()
            return answer, {key: after[key] - before[key] for key in after}

        try:
            assert admin.login("first-admin", password)[0] == 200
            state["mode"] = admin.fetch("/api/data-classes")[1]["enabled"]
            if state["mode"]:
                status, _, _ = admin.fetch(
                    "/api/data-classes/mode", {"enabled": False}, method="PUT"
                )
                if status != 200:
                    raise RuntimeError(f"Turning data classes off returned {status}")
            _, listing, _ = admin.fetch("/api/models")
            approved_before = sorted(
                row["id"] for row in listing["models"] if row.get("approved")
            )
            count = len(approved_before)
            if not preview.wait_for_report(
                preview.settled(count), timeout=HOLD_TIMEOUT
            ):
                raise RuntimeError("The model enroller did not settle before the cases")
            started = gateway_started()
            if started is None:
                raise RuntimeError("The managed gateway container was not found")

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
            token = classes.bearer(developer)
            status, _, _ = developer.fetch(
                "/api/runtime/projects",
                {"project_id": project, "name": "Model setup live " + suffix},
                method="POST",
                csrf=False,
                headers={"Authorization": "Bearer " + token},
            )
            if status != 200:
                raise RuntimeError(f"Registering the project returned {status}")

            # MSL-LIVE-01: Listed but unused.
            put_status = put_outside(name, first)
            state["gateway"] = put_status == 200
            row = wait_listed()
            settled = preview.wait_for_report(preview.settled(count), timeout=120)
            answer, reached = sent(token)
            record(
                "MSL-LIVE-01",
                put_status == 200
                and row is not None
                and not row["approved"]
                and settled
                and answer[0] != 200
                and reached == {first: 0, second: 0},
                {
                    "gateway_write": put_status,
                    "listed": row is not None,
                    "set_up": bool(row and row["approved"]),
                    "enroller": preview.enroller_reports()[-1:],
                    "gateway_status": answer[0],
                    "upstream_calls": reached,
                },
            )

            # MSL-LIVE-02: Set it up with data classes off.
            mark = len(preview.enroller_reports())
            status, result, _ = admin.fetch(
                f"/api/models/{name}/setup", {"key_choice": "none"}, method="POST"
            )
            state["setup"] = status == 200
            row = listed()
            seen = wait_after(mark, preview.settled(count + 1), timeout=90)
            answer, reached = sent(token)
            record(
                "MSL-LIVE-02",
                status == 200
                and row is not None
                and row["approved"]
                and row["approved_classes"] == []
                and seen is not None
                and answer == (200, "class answer")
                and reached == {first: 1, second: 0}
                and gateway_started() == started,
                {
                    "setup_status": status,
                    "setup_error": (result or {}).get("error"),
                    "set_up": bool(row and row["approved"]),
                    "approved_classes": row and row["approved_classes"],
                    "enroller": seen,
                    "gateway_answer": answer,
                    "upstream_calls": reached,
                    "gateway_restarted": gateway_started() != started,
                },
            )

            # MSL-LIVE-03: The model changes in the gateway, outside Keeplane.
            mark = len(preview.enroller_reports())
            put_status = put_outside(name, second)
            row = listed()
            at_once, reached_at_once = sent(token)
            seen = wait_after(mark, preview.settled(count), timeout=HOLD_TIMEOUT)
            later, reached_later = sent(token)
            record(
                "MSL-LIVE-03",
                put_status == 200
                and row is not None
                and not row["approved"]
                and at_once[0] != 200
                and reached_at_once == {first: 0, second: 0}
                and seen is not None
                and any(report.startswith(HELD) for report in seen)
                and later[0] != 200
                and reached_later == {first: 0, second: 0},
                {
                    "gateway_write": put_status,
                    "set_up": bool(row and row["approved"]),
                    "gateway_status_at_once": at_once[0],
                    "upstream_calls_at_once": reached_at_once,
                    "enroller": seen,
                    "gateway_status_after_hold": later[0],
                    "upstream_calls_after_hold": reached_later,
                },
            )

            # MSL-LIVE-04: Set it up again.
            mark = len(preview.enroller_reports())
            status, result, _ = admin.fetch(
                f"/api/models/{name}/setup", {"key_choice": "none"}, method="POST"
            )
            row = listed()
            seen = wait_after(mark, preview.settled(count + 1), timeout=HOLD_TIMEOUT)
            answer, reached = sent(token)
            record(
                "MSL-LIVE-04",
                status == 200
                and row is not None
                and row["approved"]
                and seen is not None
                and answer == (200, "class answer")
                and reached == {first: 0, second: 1}
                and gateway_started() == started,
                {
                    "setup_status": status,
                    "setup_error": (result or {}).get("error"),
                    "set_up": bool(row and row["approved"]),
                    "enroller": seen,
                    "gateway_answer": answer,
                    "upstream_calls": reached,
                    "gateway_restarted": gateway_started() != started,
                },
            )

            # MSL-LIVE-05: Remove the setup; the gateway keeps the model.
            mark = len(preview.enroller_reports())
            status, result, _ = admin.fetch(
                f"/api/models/{name}/setup", {}, method="DELETE"
            )
            if status == 200:
                state["setup"] = False
            row = listed()
            at_once, reached_at_once = sent(token)
            seen = wait_after(mark, preview.settled(count), timeout=HOLD_TIMEOUT)
            later, reached_later = sent(token)
            record(
                "MSL-LIVE-05",
                status == 200
                and (result or {}).get("gateway_model_preserved") is True
                and row is not None
                and not row["approved"]
                and at_once[0] != 200
                and reached_at_once == {first: 0, second: 0}
                and seen is not None
                and later[0] != 200
                and reached_later == {first: 0, second: 0}
                and gateway_started() == started,
                {
                    "remove_status": status,
                    "gateway_model_preserved": (result or {}).get(
                        "gateway_model_preserved"
                    ),
                    "still_listed": row is not None,
                    "set_up": bool(row and row["approved"]),
                    "gateway_status_at_once": at_once[0],
                    "upstream_calls_at_once": reached_at_once,
                    "enroller": seen,
                    "gateway_status_after_hold": later[0],
                    "upstream_calls_after_hold": reached_later,
                    "gateway_restarted": gateway_started() != started,
                },
            )
        finally:
            restore(admin, password, name, state, failures)
            if state["gateway"] and not preview.wait_for_report(
                preview.settled(len(approved_before)), timeout=HOLD_TIMEOUT
            ):
                failures.append("the model enroller did not settle after clean-up")
    cleanup = "complete" if not failures else "; ".join(failures)
    report = {
        "suite": "Spec 004 ST23/ST24 model setup on the running guarded gateway",
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
    return report


def restore(admin, password, name, state, failures):
    try:
        admin = Browser()
        if admin.login("first-admin", password)[0] != 200:
            raise RuntimeError("sign-in failed")
        if state["setup"]:
            status, _, _ = admin.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
            if status not in (200, 404):
                failures.append(f"model setup removal returned {status}")
        if state["gateway"]:
            status, _ = gateway_call("DELETE", RESOURCE_PATH + "/" + name)
            if status not in (200, 204, 404):
                failures.append(f"gateway model removal returned {status}")
        if state["developer"]:
            status, _, _ = admin.fetch(
                f"/api/users/{state['developer']}", {}, method="DELETE"
            )
            if status != 200:
                failures.append(f"developer removal returned {status}")
        if state["mode"]:
            status, _, _ = admin.fetch(
                "/api/data-classes/mode", {"enabled": True}, method="PUT"
            )
            if status != 200:
                failures.append(f"turning data classes back on returned {status}")
        admin.fetch("/sign-out", method="POST")
    except Exception as error:  # noqa: BLE001 - report, never hide, an incomplete restore.
        failures.append(f"restore raised {type(error).__name__}")


def test_model_setup_live():
    reason = preview.unavailable_reason()
    if reason:
        pytest.skip(reason)
    report = run_cases()
    assert [case["id"] for case in report["cases"]] == list(CASES)
    assert report["failed"] == 0 and report["cleanup"] == "complete"


if __name__ == "__main__":
    reason = preview.unavailable_reason()
    if reason:
        print("Not run: " + reason)
        sys.exit(2)
    result = run_cases()
    sys.exit(int(bool(result["failed"]) or result["cleanup"] != "complete"))
