"""Live edit/remove regression for a no-key outside gateway model."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from test_accounts import BASE, Browser, RUNTIME
from reporting import report_path


REPORT = report_path("2026-10-09-model-edit.json")
MODEL = "local-fixture"
PATH = f"/api/models/{MODEL}/setup"


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    cases = []
    approval_created = False
    cleanup = "not run"

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def model():
        status, listing, _ = browser.fetch("/api/models")
        return status, next((item for item in listing.get("models", []) if item["id"] == MODEL), None)

    try:
        _, initial = model()
        if initial is None or initial["approved"]:
            raise RuntimeError("The fixture must be present and unapproved before this test")
        with browser.opener.open(BASE + "/", timeout=15) as response:
            html = response.read().decode()
            page_status = response.status
        status, _, _ = browser.fetch(PATH, {
            "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
        approval_created = status == 200
        _, configured = model()
        record("EDIT-01", page_status == 200 and 'id="remove-setup-dialog"' in html and
               status == 200 and configured["approved_classes"] == ["Public"],
               {"page_status": page_status, "setup_status": status,
                "approved_classes": configured["approved_classes"]})

        edit_status, _, _ = browser.fetch(PATH, {
            "key_choice": "none", "approved_classes": ["Internal"]}, method="POST")
        _, configured = model()
        record("EDIT-02", edit_status == 200 and configured["approved_classes"] == ["Internal"],
               {"status": edit_status, "approved_classes": configured["approved_classes"]})

        unknown_status, _, _ = browser.fetch(PATH, {
            "key_choice": "none", "approved_classes": ["Unknown"]}, method="POST")
        _, configured = model()
        record("EDIT-03", unknown_status == 400 and configured["approved_classes"] == ["Internal"],
               {"status": unknown_status, "approved_classes": configured["approved_classes"]})

        denied_status, _, _ = browser.fetch(PATH, {
            "key_choice": "none", "approved_classes": ["Confidential"]},
            action=False, method="POST")
        _, configured = model()
        record("EDIT-04", denied_status == 403 and configured["approved_classes"] == ["Internal"],
               {"status": denied_status, "approved_classes": configured["approved_classes"]})

        remove_status, removed, _ = browser.fetch(PATH, {}, method="DELETE")
        if remove_status == 200:
            approval_created = False
        listing_status, outside = model()
        ask_status, _, _ = browser.fetch("/api/ask", {
            "model": MODEL, "prompt": "Reply OK."}, method="POST")
        record("EDIT-05", remove_status == 200 and removed.get("gateway_model_preserved") and
               listing_status == 200 and outside is not None and not outside["approved"] and
               ask_status == 403,
               {"remove_status": remove_status, "gateway_model_preserved": outside is not None,
                "outside_again": not outside["approved"], "ask_status": ask_status})
    finally:
        if approval_created:
            try:
                status, _, _ = browser.fetch(PATH, {}, method="DELETE")
                cleanup = "complete" if status == 200 else f"removal returned {status}"
            except Exception as error:
                cleanup = f"removal raised {type(error).__name__}"
        else:
            cleanup = "complete"
        report = {"suite": "Spec 004 local model edit Docker trial",
                  "time_utc": datetime.now(timezone.utc).isoformat(), "cases": cases,
                  "cleanup": cleanup,
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
