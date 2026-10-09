"""Live gateway definition-replacement regression on the protected Docker preview."""

import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from test_accounts import Browser, RUNTIME
from reporting import report_path


REPO = Path(__file__).resolve().parents[2]
REPORT = report_path("2026-10-09-model-replacement.json")
RESOURCE_PATH = "/api/config/resources/llm.model"
GATEWAY_SCRIPT = """
import json, sys, urllib.error, urllib.request
method, path, payload = sys.argv[1:]
data = None if payload == '-' else payload.encode()
request = urllib.request.Request('http://gateway:4000' + path, data=data, method=method)
if data is not None:
    request.add_header('Content-Type', 'application/json')
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        status, raw = response.status, response.read()
except urllib.error.HTTPError as error:
    status, raw = error.code, error.read()
try:
    body = json.loads(raw)
except ValueError:
    body = {'raw': raw.decode(errors='replace')[:300]}
print(json.dumps({'status': status, 'body': body}))
"""


def gateway_call(method, path, body=None):
    command = ["docker", "compose", "exec", "-T", "app", "python", "-c",
               GATEWAY_SCRIPT, method, path, "-" if body is None else json.dumps(body)]
    process = subprocess.run(command, check=True, cwd=REPO, capture_output=True,
                             text=True, timeout=30)
    result = json.loads(process.stdout)
    return result["status"], result["body"]


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    name = "keeplane-replace-" + uuid.uuid4().hex[:10]
    approval_path = f"/api/models/{name}/setup"
    resource = {"name": name, "provider": {"custom": {"formats": [{"type": "completions"}]}},
                "params": {"model": "mock-before", "baseUrl": "http://model:18080/v1"}}
    cases = []
    gateway_created = False
    approval_created = False
    unexpected_class_id = None
    cleanup_errors = []
    gateway_version = "unavailable"

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def listed():
        status, result, _ = browser.fetch("/api/models")
        return status, next((item for item in result.get("models", []) if item["id"] == name), None)

    def wait_listed():
        for _ in range(20):
            status, item = listed()
            if status == 200 and item is not None:
                return status, item
            time.sleep(0.2)
        return status, item

    def public_models():
        status, result, _ = browser.fetch("/api/data-classes")
        public = next((item for item in result.get("classes", []) if item["id"] == "public"), None)
        return status, public.get("approved_model_ids", []) if public else []

    try:
        runtime_status, runtime = gateway_call("GET", "/api/runtime")
        if runtime_status != 200:
            raise RuntimeError("Gateway runtime did not answer")
        gateway_version = runtime.get("build", {}).get("version", "unknown")
        create_status, created = gateway_call("PUT", RESOURCE_PATH,
                                              {"resources": [{"value": resource}]})
        gateway_created = create_status == 200
        status, item = wait_listed()
        record("REPLACE-01", create_status == 200 and status == 200 and
               item is not None and not item["approved"],
               {"create_status": create_status, "listed_status": status,
                "listed_outside": item is not None and not item["approved"],
                "gateway_resource_id": created.get("resources", [{}])[0].get("id")})

        approve_status, _, _ = browser.fetch(approval_path, {
            "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
        approval_created = approve_status == 200
        ask_status, answer, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "fixture"}, method="POST")
        record("REPLACE-02", approve_status == 200 and ask_status == 200 and
               answer.get("answer") == "mock answer",
               {"approval_status": approve_status, "ask_status": ask_status,
                "answer": answer.get("answer")})

        resource["params"]["model"] = "mock-after"
        update_status, updated = gateway_call("PUT", RESOURCE_PATH + "/" + name,
                                              {"value": resource})
        ask_status, denial, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "fixture"}, method="POST")
        list_status, current = listed()
        class_status, class_models = public_models()
        class_add_status, class_added, _ = browser.fetch("/api/data-classes", {
            "name": "replacement-" + name, "approved_model_ids": [name]}, method="POST")
        if class_add_status == 201:
            unexpected_class_id = class_added["id"]
        record("REPLACE-03", update_status == 200 and list_status == 200 and
               current is not None and not current["approved"] and ask_status == 403 and
               "changed in the gateway" in denial.get("error", "") and
               class_status == 200 and name not in class_models and class_add_status == 400,
               {"update_status": update_status,
                "gateway_revision": updated.get("resources", [{}])[0].get("revision"),
                "listed_but_unapproved": current is not None and not current["approved"],
                "ask_status": ask_status, "reason": denial.get("error"),
                "effective_class_association": name in class_models,
                "stale_class_association_status": class_add_status})

        resource["params"]["model"] = "mock-before"
        restore_status, restored = gateway_call("PUT", RESOURCE_PATH + "/" + name,
                                                {"value": resource})
        ask_status, _, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "fixture"}, method="POST")
        class_status, class_models = public_models()
        record("REPLACE-04", restore_status == 200 and ask_status == 403 and
               class_status == 200 and name not in class_models,
               {"restore_status": restore_status,
                "gateway_revision": restored.get("resources", [{}])[0].get("revision"),
                "ask_status": ask_status, "effective_class_association": name in class_models})

        reapprove_status, _, _ = browser.fetch(approval_path, {
            "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
        ask_status, answer, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "fixture"}, method="POST")
        class_status, class_models = public_models()
        record("REPLACE-05", reapprove_status == 200 and ask_status == 200 and
               answer.get("answer") == "mock answer" and class_status == 200 and name in class_models,
               {"reapproval_status": reapprove_status, "ask_status": ask_status,
                "answer": answer.get("answer"), "effective_class_association": name in class_models})
    finally:
        if unexpected_class_id:
            try:
                status, _, _ = browser.fetch(f"/api/data-classes/{unexpected_class_id}", {}, method="DELETE")
                if status != 200:
                    cleanup_errors.append(f"unexpected class removal returned {status}")
            except Exception as error:
                cleanup_errors.append(f"unexpected class removal raised {type(error).__name__}")
        if approval_created:
            try:
                status, _, _ = browser.fetch(approval_path, {}, method="DELETE")
                if status != 200:
                    cleanup_errors.append(f"approval removal returned {status}")
            except Exception as error:
                cleanup_errors.append(f"approval removal raised {type(error).__name__}")
        if gateway_created:
            try:
                status, _ = gateway_call("DELETE", RESOURCE_PATH + "/" + name)
                if status != 200:
                    cleanup_errors.append(f"gateway model removal returned {status}")
                else:
                    listed_status, listing = gateway_call("GET", "/v1/models")
                    if listed_status != 200 or name in {item.get("id") for item in listing.get("data", [])}:
                        cleanup_errors.append("gateway model remains listed after removal")
            except Exception as error:
                cleanup_errors.append(f"gateway model removal raised {type(error).__name__}")
        cleanup = "complete" if not cleanup_errors else "; ".join(cleanup_errors)
        report = {"suite": "Live gateway model replacement Docker trial",
                  "time_utc": datetime.now(timezone.utc).isoformat(),
                  "gateway_version": gateway_version,
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
