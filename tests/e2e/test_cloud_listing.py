"""Live Spec 004 native-provider listing and outside-model boundary."""

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from test_accounts import Browser, RUNTIME
from test_model_replacement import RESOURCE_PATH, gateway_call
from reporting import report_path


REPORT = report_path("2026-10-09-cloud-listing.json")


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    suffix = uuid.uuid4().hex[:10]
    openai_name = "keeplane-openai-list-" + suffix
    anthropic_name = "keeplane-anthropic-list-" + suffix
    cases = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail", "observed": observed})

    def listed():
        status, result, _ = browser.fetch("/api/models")
        return status, {item["id"]: item for item in result.get("models", [])}

    resources = [{"value": {"name": name, "provider": provider,
                             "params": {"model": "mock-local", "baseUrl": "http://model:18080/v1"}}}
                 for name, provider in ((openai_name, "openAI"), (anthropic_name, "anthropic"))]
    approved = False
    try:
        put_status, _ = gateway_call("PUT", RESOURCE_PATH, {"resources": resources})
        visible = {}
        list_status = 0
        for _ in range(15):
            list_status, visible = listed()
            if openai_name in visible and anthropic_name in visible:
                break
            time.sleep(0.2)
        openai = visible.get(openai_name, {})
        anthropic = visible.get(anthropic_name, {})
        record("CLOUD-01", put_status == 200 and list_status == 200 and
               openai.get("provider") == "OpenAI" and openai.get("kind") == "cloud" and
               openai.get("approved") is False and openai.get("key_choice") is None and
               anthropic.get("provider") == "Anthropic" and anthropic.get("kind") == "cloud" and
               anthropic.get("approved") is False and anthropic.get("key_choice") is None,
               {"gateway_put_http": put_status, "list_http": list_status,
                "openai": {k: openai.get(k) for k in ("provider", "kind", "approved", "key_choice")},
                "anthropic": {k: anthropic.get(k) for k in ("provider", "kind", "approved", "key_choice")}})

        openai_status, _, _ = browser.fetch("/api/ask", {"model": openai_name, "prompt": "Reply OK."}, method="POST")
        anthropic_status, _, _ = browser.fetch("/api/ask", {"model": anthropic_name, "prompt": "Reply OK."}, method="POST")
        record("CLOUD-02", openai_status == 403 and anthropic_status == 403,
               {"openai_http": openai_status, "anthropic_http": anthropic_status})

        setup_status, setup, _ = browser.fetch(f"/api/models/{openai_name}/setup", {
            "key_choice": "none", "approved_classes": ["Public"]}, method="POST")
        approved = setup_status == 200
        list_status, visible = listed()
        ready = visible.get(openai_name, {})
        ask_status, answer, _ = browser.fetch("/api/ask", {"model": openai_name,
                                             "prompt": "Reply OK."}, method="POST")
        record("CLOUD-03", setup_status == 200 and setup.get("key_choice") == "none" and
               list_status == 200 and ready.get("approved") is True and
               ready.get("approved_classes") == ["Public"] and ask_status == 200 and
               answer.get("answer") == "mock answer",
               {"setup_http": setup_status, "list_http": list_status,
                "approved": ready.get("approved"), "key_choice": ready.get("key_choice"),
                "ask_http": ask_status, "answer": answer.get("answer")})
    finally:
        approval_status, _, _ = browser.fetch(f"/api/models/{openai_name}/setup", {}, method="DELETE") if approved else (404, None, None)
        openai_delete, _ = gateway_call("DELETE", RESOURCE_PATH + "/" + openai_name)
        anthropic_delete, _ = gateway_call("DELETE", RESOURCE_PATH + "/" + anthropic_name)
        record("CLOUD-04", approval_status in (200, 404) and openai_delete in (200, 404) and
               anthropic_delete in (200, 404),
               {"approval_delete_http": approval_status, "openai_delete_http": openai_delete,
                "anthropic_delete_http": anthropic_delete})
        report = {"suite": "Spec 004 native cloud model listing with local mock",
                  "time_utc": datetime.now(timezone.utc).isoformat(), "cases": cases,
                  "passed": sum(case["verdict"] == "pass" for case in cases),
                  "failed": sum(case["verdict"] == "fail" for case in cases)}
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{report['passed']} passed, {report['failed']} failed; {REPORT}")
        for case in cases:
            print(case["id"], case["verdict"], case["observed"])
        if report["failed"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
