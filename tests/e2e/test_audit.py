"""Authenticated Spec 006 Audit Docker evidence with a named trial class."""

import json
import secrets
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode

from test_accounts import BASE, Browser, RUNTIME
from reporting import report_path
from restart_preview import restart_app


REPO = Path(__file__).resolve().parents[2]
REPORT = report_path("2026-10-10-audit-developer.json")


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    name = "audit-trial-" + uuid.uuid4().hex[:8]
    class_id = None
    developer_id = None
    cases = []
    cleanup_errors = []
    original_options = None
    original_mode = None

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def options():
        status, result, _ = browser.fetch("/api/audit/options")
        if status != 200:
            raise RuntimeError(f"Audit options returned HTTP {status}: {result}")
        return result["options"]

    def records(kind="all", search="", page=1):
        parameters = urlencode({"kind": kind, "search": search, "page": page})
        status, result, _ = browser.fetch("/api/audit/records?" + parameters)
        if status != 200:
            raise RuntimeError(f"Audit records returned HTTP {status}: {result}")
        return result

    def switch(kind, enabled):
        status, result, _ = browser.fetch("/api/audit/options/" + kind,
                                          {"enabled": enabled}, method="PUT")
        if status != 200:
            raise RuntimeError(f"Audit switch returned HTTP {status}: {result}")

    try:
        with browser.opener.open(BASE + "/audit", timeout=15) as response:
            page_status = response.status
            page_url = response.url
            html = response.read().decode()
        original_options = options()
        original_mode = browser.fetch("/api/data-classes")[1]["enabled"]
        if not original_mode:
            mode_status, _, _ = browser.fetch("/api/data-classes/mode",
                                              {"enabled": True}, method="PUT")
            if mode_status != 200:
                raise RuntimeError("Could not enable data classes for Audit cases")
        baseline = records()["total"]
        identity_status, identity, _ = browser.fetch("/api/identity")
        record("AUD-01", page_status == 200 and 'id="root"' in html and
               page_url == BASE + "/app/audit" and identity_status == 200 and
               set(original_options) == {"settings", "held_requests", "model_answers"},
               {"page_status": page_status, "actor": identity.get("username"),
                "original_options": original_options, "existing_records": baseline})

        switch("held_requests", False)
        switch("model_answers", False)
        switch("settings", True)
        status, added, _ = browser.fetch("/api/data-classes",
                                          {"name": name, "approved_model_ids": []}, method="POST")
        if status == 201:
            class_id = added["id"]
        after_add = records()
        added_record = next((item for item in after_add["records"] if name in item["what"]), None)
        record("AUD-02", status == 201 and after_add["total"] == baseline + 1 and
               added_record is not None and added_record["who"] == "first-admin" and
               added_record["when"].endswith("+00:00") and
               not options()["held_requests"] and not options()["model_answers"],
               {"add_status": status, "actor": added_record["who"] if added_record else None,
                "records_added": after_add["total"] - baseline})

        no_op_status, _, _ = browser.fetch(f"/api/data-classes/{class_id}",
                                            {"name": name, "approved_model_ids": []}, method="PUT")
        invalid_status, _, _ = browser.fetch("/api/data-classes",
                                              {"name": name, "approved_model_ids": []}, method="POST")
        unchanged_count = records()["total"]
        record("AUD-05", no_op_status == 200 and invalid_status == 409 and
               unchanged_count == baseline + 1,
               {"no_op_status": no_op_status, "invalid_status": invalid_status,
                "new_records": unchanged_count - baseline})

        renamed = name + "-changed"
        edit_status, _, _ = browser.fetch(f"/api/data-classes/{class_id}",
                                           {"name": renamed, "approved_model_ids": []}, method="PUT")
        remove_status, _, _ = browser.fetch(f"/api/data-classes/{class_id}", {}, method="DELETE")
        if remove_status == 200:
            class_id = None
        matching = records(search=name)
        descriptions = [item["what"] for item in matching["records"]]
        record("AUD-03", edit_status == 200 and remove_status == 200 and
               matching["total"] == 3 and descriptions[0].startswith("Removed data class") and
               descriptions[1].startswith("Changed data class") and
               descriptions[2].startswith("Added data class"),
               {"edit_status": edit_status, "remove_status": remove_status,
                "descriptions": descriptions})

        filtered = records(kind="settings", search=name)
        held = records(kind="held_requests", search=name)
        missing = records(search="does-not-exist-" + name)
        record("AUD-04", filtered["total"] == 3 and held["total"] == 0 and
               missing["total"] == 0 and len(filtered["records"]) <= 25,
               {"settings_matches": filtered["total"], "held_matches": held["total"],
                "nonmatching_search": missing["total"]})

        switch("settings", False)
        off_name = name + "-off"
        status, added, _ = browser.fetch("/api/data-classes",
                                          {"name": off_name, "approved_model_ids": []}, method="POST")
        if status == 201:
            class_id = added["id"]
        off_count = records()["total"]
        record("AUD-06", status == 201 and off_count == baseline + 3,
               {"add_status": status, "new_records_while_off": off_count - baseline - 3})
        if class_id:
            remove_status, _, _ = browser.fetch(f"/api/data-classes/{class_id}", {}, method="DELETE")
            if remove_status == 200:
                class_id = None

        denied_status, _, _ = browser.fetch("/api/audit/options/settings",
                                              {"enabled": True}, action=False, method="PUT")
        record("AUD-08", denied_status == 403 and not options()["settings"],
               {"denied_status": denied_status, "settings_still_off": not options()["settings"]})

        developer_name = "audit-developer-" + uuid.uuid4().hex[:8]
        developer_password = secrets.token_urlsafe(18)
        create_status, created, _ = browser.fetch("/api/users", {
            "username": developer_name, "password": developer_password,
            "role": "developer"}, method="POST")
        if create_status == 201:
            developer_id = created["id"]
        developer = Browser()
        developer_status, developer_url, _, _, _ = developer.login(developer_name, developer_password)
        developer_api_status, _, _ = developer.fetch("/api/audit/records")
        anonymous_status, _, _ = Browser().fetch("/api/audit/records")
        record("AUD-09", create_status == 201 and developer_status == 200 and
               developer_url == BASE + "/app/" and developer_api_status == 403 and
               anonymous_status == 401,
               {"create_status": create_status, "developer_login_status": developer_status,
                "developer_api_status": developer_api_status,
                "anonymous_api_status": anonymous_status})

        restart_app(BASE)
        for _ in range(30):
            try:
                persisted_options = options()
                persisted_records = records()
                break
            except (URLError, ConnectionError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError("Audit API did not recover after control-plane restart")
        record("AUD-07", not persisted_options["settings"] and
               persisted_records["total"] == baseline + 3 and
               len(persisted_records["records"]) <= 25,
               {"settings_after_restart": persisted_options["settings"],
                "records_after_restart": persisted_records["total"],
                "page_rows": len(persisted_records["records"])})
    finally:
        if class_id:
            try:
                status, _, _ = browser.fetch(f"/api/data-classes/{class_id}", {}, method="DELETE")
                if status != 200:
                    cleanup_errors.append(f"class removal returned {status}")
            except Exception as error:
                cleanup_errors.append(f"class removal raised {type(error).__name__}")
        if developer_id:
            try:
                status, _, _ = browser.fetch("/api/users/" + developer_id, {}, method="DELETE")
                if status != 200:
                    cleanup_errors.append(f"developer removal returned {status}")
            except Exception as error:
                cleanup_errors.append(f"developer removal raised {type(error).__name__}")
        if original_options is not None:
            for kind, enabled in original_options.items():
                for attempt in range(30):
                    try:
                        switch(kind, enabled)
                        break
                    except (URLError, ConnectionError, RuntimeError) as error:
                        if attempt == 29:
                            cleanup_errors.append(f"restoring {kind} raised {type(error).__name__}")
                        else:
                            time.sleep(1)
        if original_mode is False:
            try:
                status, _, _ = browser.fetch("/api/data-classes/mode",
                                              {"enabled": False}, method="PUT")
                if status != 200:
                    cleanup_errors.append(f"restoring class mode returned {status}")
            except Exception as error:
                cleanup_errors.append(f"restoring class mode raised {type(error).__name__}")
        report = {"suite": "Spec 006 Audit protected Docker preview",
                  "time_utc": datetime.now(timezone.utc).isoformat(),
                  "cases": cases, "cleanup": "complete" if not cleanup_errors else cleanup_errors,
                  "passed": sum(case["verdict"] == "pass" for case in cases),
                  "failed": sum(case["verdict"] == "fail" for case in cases)}
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{report['passed']} passed, {report['failed']} failed; cleanup {report['cleanup']}")
        for case in cases:
            print(case["id"], case["verdict"], case["observed"])
        if report["failed"] or cleanup_errors:
            sys.exit(1)


if __name__ == "__main__":
    main()
