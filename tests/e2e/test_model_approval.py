"""Live Spec 004 outside-model approval regression for the Docker trial."""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

from test_accounts import BASE, Browser, RUNTIME
from reporting import report_path
from restart_preview import restart_app


REPO = Path(__file__).resolve().parents[2]
REPORT = report_path("2026-10-09-model-approval.json")
MODEL = "local-fixture"
DYNAMIC_MODEL = "second-local"


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    cases = []
    touched = set()
    cleanup = "not run"

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def model(name=MODEL):
        status, listing, _ = browser.fetch("/api/models")
        found = next((entry for entry in listing.get("models", []) if entry["id"] == name), None)
        return status, found

    def wait_model(name):
        for _ in range(30):
            try:
                status, found = model(name)
                if status == 200 and found is not None:
                    return found
            except (URLError, ConnectionError):
                pass
            time.sleep(1)
        raise RuntimeError("Account preview did not return the gateway model after restart")

    path = f"/api/models/{MODEL}/setup"
    try:
        status, found = model()
        if found is None or found["approved"]:
            raise RuntimeError("The fixture must be present and unapproved before this test")
        with browser.opener.open(BASE + "/", timeout=15) as response:
            page = response.read().decode()
        record("MODEL-01", status == 200 and found is not None and not found["approved"] and
               found["key_choice"] is None and not found["approved_classes"] and
               'id="setup-dialog"' in page and "Set up model" in page,
               {"status": status, "outside": found is not None and not found["approved"],
                "setup_dialog": 'id="setup-dialog"' in page})

        status, result, _ = browser.fetch("/api/ask", {"model": MODEL, "prompt": "Reply OK."}, method="POST")
        record("MODEL-02", status == 403,
               {"status": status, "error": result.get("error")})

        payload = {"key_choice": "none", "approved_classes": ["Public", "Internal"]}
        status, _, _ = browser.fetch(path, payload, action=False, method="POST")
        record("MODEL-03", status == 403, {"status": status})

        registration_status, _, _ = browser.fetch("/api/models", {
            "name": "model-approval-forbidden", "model": "mock-local", "source": "fixture"},
            action=False, method="POST")
        record("MODEL-10", registration_status == 403,
               {"registration_without_action_status": registration_status})

        wrong_key, _, _ = browser.fetch(path, {"key_choice": "shared",
            "approved_classes": ["Public"]}, method="POST")
        wrong_class, _, _ = browser.fetch(path, {"key_choice": "none",
            "approved_classes": ["Restricted"]}, method="POST")
        _, found = model()
        record("MODEL-04", wrong_key == 400 and wrong_class == 400 and not found["approved"],
               {"wrong_key_status": wrong_key, "wrong_class_status": wrong_class,
                "still_outside": not found["approved"]})

        setup_status, setup, _ = browser.fetch(path, payload, method="POST")
        if setup_status == 200:
            touched.add(MODEL)
        status, found = model()
        record("MODEL-05", setup_status == 200 and status == 200 and found["approved"] and
               found["key_choice"] == "none" and found["approved_classes"] == ["Public", "Internal"],
               {"setup_status": setup_status, "listed_approval": found.get("approved"),
                "classes": found.get("approved_classes")})

        status, answer, _ = browser.fetch("/api/ask", {"model": MODEL, "prompt": "Reply OK."}, method="POST")
        record("MODEL-06", status == 200 and answer.get("answer") == "mock answer",
               {"status": status, "answer": answer.get("answer")})

        restart_app(BASE)
        found = wait_model(MODEL)
        status, answer, _ = browser.fetch("/api/ask", {"model": MODEL, "prompt": "Reply OK."}, method="POST")
        record("MODEL-07", found["approved"] and status == 200 and answer.get("answer") == "mock answer",
               {"persisted_approval": found["approved"], "answer_status": status})

        removed_status, removed, _ = browser.fetch(path, {}, method="DELETE")
        if removed_status == 200:
            touched.discard(MODEL)
        status, found = model()
        denied_status, _, _ = browser.fetch("/api/ask", {"model": MODEL, "prompt": "Reply OK."}, method="POST")
        record("MODEL-08", removed_status == 200 and removed.get("gateway_model_preserved") and
               status == 200 and not found["approved"] and denied_status == 403,
               {"removed_status": removed_status, "still_in_gateway": found is not None,
                "outside_again": not found["approved"], "ask_status": denied_status})

        dynamic = wait_model(DYNAMIC_MODEL)
        if dynamic["approved"]:
            raise RuntimeError("The dynamic gateway model must be unapproved before this test")
        dynamic_path = f"/api/models/{DYNAMIC_MODEL}/setup"
        setup_status, _, _ = browser.fetch(dynamic_path, payload, method="POST")
        if setup_status == 200:
            touched.add(DYNAMIC_MODEL)
        restart_app(BASE)
        dynamic = wait_model(DYNAMIC_MODEL)
        answer_status, answer, _ = browser.fetch("/api/ask", {
            "model": DYNAMIC_MODEL, "prompt": "Reply OK."}, method="POST")
        record("MODEL-09", setup_status == 200 and dynamic["approved"] and answer_status == 200 and
               answer.get("answer") == "mock answer",
               {"setup_status": setup_status, "persisted_approval": dynamic["approved"],
                "answer_status": answer_status})
    finally:
        try:
            failures = 0
            for name in touched:
                status = 0
                for _ in range(20):
                    try:
                        status, _, _ = browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
                    except (URLError, ConnectionError):
                        status = 0
                    if status == 200:
                        break
                    time.sleep(1)
                if status != 200:
                    failures += 1
            cleanup = "complete" if not failures else f"{failures} approvals remained"
        except Exception as error:
            cleanup = f"failed: {type(error).__name__}"
        report = {"suite": "Spec 004 outside-model approval Docker trial",
                  "time_utc": datetime.now(timezone.utc).isoformat(),
                  "cases": cases, "cleanup": cleanup,
                  "passed": sum(case["verdict"] == "pass" for case in cases),
                  "failed": sum(case["verdict"] == "fail" for case in cases)}
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{report['passed']} passed, {report['failed']} failed; cleanup {cleanup}; {REPORT}")
        for case in cases:
            print(case["id"], case["verdict"], case["observed"])
        if report["failed"] or cleanup != "complete":
            sys.exit(1)


if __name__ == "__main__":
    main()
