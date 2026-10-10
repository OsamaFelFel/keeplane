"""Live Spec 005 starter class regression for the protected Docker trial."""

import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

from test_accounts import BASE, Browser, RUNTIME
from reporting import report_path


REPO = Path(__file__).resolve().parents[2]
REPORT = report_path("2026-10-09-data-classes.json")
MODEL = "local-fixture"


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    name = "trial-" + uuid.uuid4().hex[:8]
    class_id = None
    approval_created = False
    original_mode = None
    cases = []
    cleanup = "not run"

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def classes():
        status, result, _ = browser.fetch("/api/data-classes")
        return status, result.get("classes", [])

    def mode(enabled):
        return browser.fetch("/api/data-classes/mode", {"enabled": enabled}, method="PUT")

    def model():
        status, result, _ = browser.fetch("/api/models")
        return status, next((item for item in result.get("models", []) if item["id"] == MODEL), None)

    try:
        original_mode = browser.fetch("/api/data-classes")[1]["enabled"]
        off_status, _, _ = mode(False)
        off_list_status, off_list, _ = browser.fetch("/api/data-classes")
        off_add_status, _, _ = browser.fetch("/api/data-classes", {
            "name": name, "approved_model_ids": []}, method="POST")
        record("CLASS-00", off_status == 200 and off_list_status == 200 and
               off_list == {"enabled": False, "classes": []} and off_add_status == 409,
               {"mode_status": off_status, "listing": off_list, "add_while_off": off_add_status})
        off_setup_status, _, _ = browser.fetch(f"/api/models/{MODEL}/setup", {
            "key_choice": "none"}, method="POST")
        _, off_model = model()
        on_status, _, _ = mode(True)
        _, on_model = model()
        off_setup_removed, _, _ = browser.fetch(f"/api/models/{MODEL}/setup", {}, method="DELETE")
        record("CLASS-10", off_setup_status == 200 and off_model["approved"] and
               off_model["approved_classes"] == [] and on_model["approved"] and
               on_model["approved_classes"] == [] and off_setup_removed == 200,
               {"setup_while_off": off_setup_status, "approval_after_enable": on_model["approved_classes"],
                "cleanup_status": off_setup_removed})
        status, initial = classes()
        with browser.opener.open(BASE + "/data-classes", timeout=15) as response:
            page_status = response.status
            page = response.read().decode()
        _, initial_model = model()
        if initial_model is None or initial_model["approved"]:
            raise RuntimeError("The fixture must be present and unapproved before this test")
        names = [item["name"] for item in initial]
        record("CLASS-01", on_status == 200 and status == 200 and
               names[:3] == ["Public", "Internal", "Confidential"] and
               page_status == 200 and 'id="root"' in page,
               {"status": status, "starter_names": names[:3], "page_status": page_status})

        setup_status, _, _ = browser.fetch(f"/api/models/{MODEL}/setup", {
            "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
        if setup_status == 200:
            approval_created = True
        mode(False)
        _, setup_while_off = model()
        mode(True)
        _, setup_again = model()
        record("CLASS-09", setup_status == 200 and setup_while_off["approved"] and
               setup_again["approved_classes"] == ["Public"],
               {"setup_while_off": setup_while_off["approved"],
                "approval_after_reenable": setup_again["approved_classes"]})
        add_status, added, _ = browser.fetch("/api/data-classes", {
            "name": name, "approved_model_ids": [MODEL]}, method="POST")
        if add_status == 201:
            class_id = added["id"]
        status, listing = classes()
        _, configured = model()
        created = next((item for item in listing if item["id"] == class_id), None)
        record("CLASS-02", setup_status == 200 and add_status == 201 and status == 200 and
               created is not None and created["approved_model_ids"] == [MODEL] and
               name in configured["approved_classes"],
               {"setup_status": setup_status, "add_status": add_status,
                "class_has_model": created is not None and MODEL in created["approved_model_ids"],
                "model_has_class": name in configured["approved_classes"]})

        duplicate_status, _, _ = browser.fetch("/api/data-classes", {
            "name": name.upper(), "approved_model_ids": []}, method="POST")
        record("CLASS-03", duplicate_status == 409, {"status": duplicate_status})
        unknown_status, _, _ = browser.fetch("/api/data-classes", {
            "name": name + "-unknown", "approved_model_ids": ["not-approved"]}, method="POST")
        record("CLASS-04", unknown_status == 400, {"status": unknown_status})

        renamed = name + " renamed"
        edit_status, _, _ = browser.fetch(f"/api/data-classes/{class_id}", {
            "name": renamed, "approved_model_ids": [MODEL]}, method="PUT")
        _, listing = classes()
        _, configured = model()
        record("CLASS-05", edit_status == 200 and renamed in [item["name"] for item in listing] and
               name not in [item["name"] for item in listing] and
               renamed in configured["approved_classes"] and name not in configured["approved_classes"],
               {"status": edit_status, "renamed_in_classes": renamed in [item["name"] for item in listing],
                "renamed_on_model": renamed in configured["approved_classes"]})

        subprocess.run(["docker", "compose", "--env-file", str(RUNTIME / ".env"),
                        "restart", "app"], check=True, cwd=REPO, capture_output=True, text=True)
        for _ in range(30):
            try:
                status, listing = classes()
                if status == 200:
                    break
            except (URLError, ConnectionError):
                pass
            time.sleep(1)
        _, configured = model()
        record("CLASS-06", any(item["id"] == class_id and item["name"] == renamed for item in listing) and
               renamed in configured["approved_classes"],
               {"persisted_class": any(item["id"] == class_id and item["name"] == renamed for item in listing),
                "persisted_model_approval": renamed in configured["approved_classes"]})

        denied_status, _, _ = browser.fetch("/api/data-classes", {
            "name": name + "-denied", "approved_model_ids": []}, action=False, method="POST")
        record("CLASS-08", denied_status == 403, {"status": denied_status})

        remove_status, _, _ = browser.fetch(f"/api/data-classes/{class_id}", {}, method="DELETE")
        if remove_status == 200:
            class_id = None
        _, listing = classes()
        _, configured = model()
        record("CLASS-07", remove_status == 200 and renamed not in [item["name"] for item in listing] and
               configured["approved"] and configured["approved_classes"] == ["Public"],
               {"remove_status": remove_status, "class_absent": renamed not in [item["name"] for item in listing],
                "remaining_approval": configured["approved_classes"]})
    finally:
        failures = []
        mode(True)
        if class_id:
            try:
                status, _, _ = browser.fetch(f"/api/data-classes/{class_id}", {}, method="DELETE")
                if status != 200:
                    failures.append(f"class removal returned {status}")
            except Exception as error:
                failures.append(f"class removal raised {type(error).__name__}")
        if approval_created:
            try:
                status, _, _ = browser.fetch(f"/api/models/{MODEL}/setup", {}, method="DELETE")
                if status != 200:
                    failures.append(f"model approval removal returned {status}")
            except Exception as error:
                failures.append(f"model approval removal raised {type(error).__name__}")
        if original_mode is not None:
            try:
                mode(original_mode)
            except Exception as error:
                failures.append(f"mode restore raised {type(error).__name__}")
        cleanup = "complete" if not failures else "; ".join(failures)
        report = {"suite": "Spec 005 starter data-class Docker trial",
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
