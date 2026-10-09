"""Live owned-versus-outside model removal against the protected Docker preview."""

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from test_accounts import BASE, Browser, RUNTIME
from test_model_replacement import RESOURCE_PATH, gateway_call
from reporting import report_path


REPORT = report_path("2026-10-09-model-removal.json")


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    suffix = uuid.uuid4().hex[:10]
    owned_name = "keeplane-remove-" + suffix
    outside_name = "outside-remove-" + suffix
    changed_name = "keeplane-changed-" + suffix
    names = (owned_name, outside_name, changed_name)
    cases = []
    cleanup = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def listing(name):
        status, result, _ = browser.fetch("/api/models")
        return status, next((item for item in result.get("models", []) if item["id"] == name), None)

    def resource_exists(name):
        status, result = gateway_call("GET", RESOURCE_PATH)
        return status == 200 and name in {item.get("id") for item in result.get("resources", [])}

    def register_outside(name):
        resource = {"name": name, "provider": {"custom": {"formats": [{"type": "completions"}]}},
                    "params": {"model": "mock-local", "baseUrl": "http://model:18080/v1"}}
        status, _ = gateway_call("PUT", RESOURCE_PATH, {"resources": [{"value": resource}]})
        return status, resource

    try:
        add_status, _, _ = browser.fetch("/api/models", {
            "name": owned_name, "model": "mock-local", "source": "fixture",
            "approved_classes": ["Public"]}, method="POST")
        list_status, owned = listing(owned_name)
        ask_status, answer, _ = browser.fetch("/api/ask", {
            "model": owned_name, "prompt": "Reply OK."}, method="POST")
        record("REMOVE-01", add_status == 200 and list_status == 200 and
               owned is not None and owned["approved"] and owned["owned_by_keeplane"] and
               ask_status == 200 and answer.get("answer") == "mock answer",
               {"add_http": add_status, "list_http": list_status,
                "owned": owned.get("owned_by_keeplane") if owned else None,
                "ask_http": ask_status})

        denied_status, _, _ = browser.fetch(f"/api/models/{owned_name}/setup", {},
                                            action=False, method="DELETE")
        _, still_owned = listing(owned_name)
        record("REMOVE-02", denied_status == 403 and still_owned is not None and
               still_owned["approved"] and resource_exists(owned_name),
               {"delete_http": denied_status, "still_approved":
                still_owned.get("approved") if still_owned else None,
                "gateway_resource_present": resource_exists(owned_name)})

        delete_status, deleted, _ = browser.fetch(f"/api/models/{owned_name}/setup", {}, method="DELETE")
        for _ in range(15):
            if not resource_exists(owned_name):
                break
            time.sleep(0.2)
        _, after = listing(owned_name)
        ask_status, _, _ = browser.fetch("/api/ask", {
            "model": owned_name, "prompt": "Reply OK."}, method="POST")
        record("REMOVE-03", delete_status == 200 and not deleted.get("gateway_model_preserved") and
               not resource_exists(owned_name) and (after is None or not after["approved"]) and
               ask_status == 403,
               {"delete_http": delete_status, "gateway_model_preserved":
                deleted.get("gateway_model_preserved"),
                "gateway_resource_present": resource_exists(owned_name),
                "approved_after": after.get("approved") if after else None,
                "ask_http": ask_status})

        outside_status, _ = register_outside(outside_name)
        setup_status, _, _ = browser.fetch(f"/api/models/{outside_name}/setup", {
            "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
        _, outside = listing(outside_name)
        remove_status, removed, _ = browser.fetch(f"/api/models/{outside_name}/setup", {}, method="DELETE")
        _, after = listing(outside_name)
        ask_status, _, _ = browser.fetch("/api/ask", {
            "model": outside_name, "prompt": "Reply OK."}, method="POST")
        record("REMOVE-04", outside_status == 200 and setup_status == 200 and
               outside is not None and outside["approved"] and not outside["owned_by_keeplane"] and
               remove_status == 200 and removed.get("gateway_model_preserved") and
               resource_exists(outside_name) and after is not None and not after["approved"] and
               ask_status == 403,
               {"gateway_create_http": outside_status, "setup_http": setup_status,
                "owned": outside.get("owned_by_keeplane") if outside else None,
                "delete_http": remove_status, "gateway_preserved": resource_exists(outside_name),
                "ask_http": ask_status})

        add_status, _, _ = browser.fetch("/api/models", {
            "name": changed_name, "model": "mock-local", "source": "fixture",
            "approved_classes": ["Public"]}, method="POST")
        changed = {"name": changed_name,
                   "provider": {"custom": {"formats": [{"type": "completions"}]}},
                   "params": {"model": "mock-after", "baseUrl": "http://model:18080/v1"}}
        update_status, _ = gateway_call("PUT", RESOURCE_PATH + "/" + changed_name,
                                        {"value": changed})
        denied_status, denial, _ = browser.fetch(f"/api/models/{changed_name}/setup", {},
                                                  method="DELETE")
        ask_status, _, _ = browser.fetch("/api/ask", {
            "model": changed_name, "prompt": "Reply OK."}, method="POST")
        record("REMOVE-05", add_status == 200 and update_status == 200 and
               denied_status == 409 and resource_exists(changed_name) and ask_status == 403,
               {"add_http": add_status, "update_http": update_status,
                "delete_http": denied_status, "reason": denial.get("error"),
                "gateway_preserved": resource_exists(changed_name), "ask_http": ask_status})

        setup_status, setup, _ = browser.fetch(f"/api/models/{changed_name}/setup", {
            "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
        _, configured = listing(changed_name)
        remove_status, removed, _ = browser.fetch(f"/api/models/{changed_name}/setup", {},
                                                   method="DELETE")
        record("REMOVE-06", setup_status == 200 and not setup.get("owned_by_keeplane") and
               configured is not None and not configured["owned_by_keeplane"] and
               remove_status == 200 and removed.get("gateway_model_preserved") and
               resource_exists(changed_name),
               {"setup_http": setup_status, "owned_after_setup":
                configured.get("owned_by_keeplane") if configured else None,
                "remove_http": remove_status,
                "gateway_preserved": resource_exists(changed_name)})

        with browser.opener.open(BASE + "/", timeout=15) as response:
            page_status, page = response.status, response.read().decode()
        with browser.opener.open(BASE + "/app.js", timeout=15) as response:
            script_status, script = response.status, response.read().decode()
        record("REMOVE-07", page_status == 200 and script_status == 200 and
               'id="remove-setup-dialog"' in page and
               'model.owned_by_keeplane' in script and
               'removes it from the gateway' in script,
               {"page_http": page_status, "script_http": script_status,
                "dialog_present": 'id="remove-setup-dialog"' in page})
    finally:
        for name in names:
            try:
                status, _, _ = browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
                if status == 409:
                    browser.fetch(f"/api/models/{name}/setup", {
                        "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
                    browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
                resource_status, _ = gateway_call("DELETE", RESOURCE_PATH + "/" + name)
                cleanup.append({"name": name, "setup_http": status,
                                "gateway_http": resource_status})
            except Exception as error:
                cleanup.append({"name": name, "error": type(error).__name__})
        report = {"suite": "Spec 004 local model removal Docker trial",
                  "time_utc": datetime.now(timezone.utc).isoformat(),
                  "cases": cases, "cleanup": cleanup,
                  "passed": sum(item["verdict"] == "pass" for item in cases),
                  "failed": sum(item["verdict"] == "fail" for item in cases)}
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{report['passed']} passed, {report['failed']} failed; {REPORT}")
        for case in cases:
            print(case["id"], case["verdict"], case["observed"])
        if report["failed"] or any(item.get("error") for item in cleanup):
            sys.exit(1)


if __name__ == "__main__":
    main()
