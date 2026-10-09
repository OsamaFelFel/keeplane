"""Live one-step model registration and approval against the protected preview."""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from test_accounts import BASE, Browser, RUNTIME
from test_model_replacement import RESOURCE_PATH, gateway_call
from reporting import report_path


REPORT = report_path("2026-10-09-model-add.json")


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    name = "keeplane-add-" + uuid.uuid4().hex[:10]
    bad_name = name + "-no-answer"
    runner_name = name + "-runner"
    cases = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail", "observed": observed})

    try:
        with browser.opener.open(BASE + "/", timeout=15) as response:
            status, html = response.status, response.read().decode()
        class_status, classes, _ = browser.fetch("/api/data-classes")
        record("ADD-01", status == 200 and class_status == 200 and
               'id="add-class-choices"' in html and {"Public", "Internal"}.issubset(
                   {item["name"] for item in classes.get("classes", [])}),
               {"page_http": status, "classes_http": class_status,
                "add_class_choices_present": 'id="add-class-choices"' in html})

        missing_status, missing, _ = browser.fetch("/api/models", {
            "name": name, "model": "mock-local", "source": "fixture"}, method="POST")
        invalid_status, invalid, _ = browser.fetch("/api/models", {
            "name": name, "model": "mock-local", "source": "fixture",
            "approved_classes": ["Nonexistent"]}, method="POST")
        gateway_status, resources = gateway_call("GET", RESOURCE_PATH)
        record("ADD-02", missing_status == 400 and invalid_status == 400 and
               gateway_status == 200 and
               name not in {item.get("id") for item in resources.get("resources", [])},
               {"missing_http": missing_status, "invalid_http": invalid_status,
                "gateway_http": gateway_status, "missing_error": missing.get("error"),
                "invalid_error": invalid.get("error")})

        add_status, added, _ = browser.fetch("/api/models", {
            "name": name, "model": "mock-local", "source": "fixture",
            "approved_classes": ["Public", "Internal"]}, method="POST")
        list_status, listing, _ = browser.fetch("/api/models")
        found = next((item for item in listing.get("models", []) if item["id"] == name), None)
        record("ADD-03", add_status == 200 and added.get("approved_classes") ==
               ["Public", "Internal"] and list_status == 200 and found is not None and
               found["approved"] and found["approved_classes"] == ["Public", "Internal"],
               {"add_http": add_status, "list_http": list_status, "approved":
                found.get("approved") if found else None, "classes":
                found.get("approved_classes") if found else None})

        ask_status, answer, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "Reply OK."}, method="POST")
        class_status, classes, _ = browser.fetch("/api/data-classes")
        approved = {item["name"] for item in classes.get("classes", [])
                    if name in item.get("approved_model_ids", [])}
        record("ADD-04", ask_status == 200 and answer.get("answer") == "mock answer" and
               class_status == 200 and approved == {"Public", "Internal"},
               {"ask_http": ask_status, "answer": answer.get("answer"),
                "approved_classes": sorted(approved)})

        repeat_status, repeat, _ = browser.fetch("/api/models", {
            "name": name, "model": "mock-local", "source": "fixture",
            "approved_classes": ["Public"]}, method="POST")
        _, listing, _ = browser.fetch("/api/models")
        found = next((item for item in listing.get("models", []) if item["id"] == name), None)
        record("ADD-05", repeat_status == 200 and repeat.get("existing") is True and
               found is not None and found["approved_classes"] == ["Public", "Internal"],
               {"repeat_http": repeat_status, "existing": repeat.get("existing"),
                "preserved_classes": found.get("approved_classes") if found else None})

        runner_status, runner_added, _ = browser.fetch("/api/models", {
            "name": runner_name, "model": "qwen2.5-coder:0.5b", "source": "runner",
            "address": "http://qwen:8080", "approved_classes": ["Public"]}, method="POST")
        runner_ask_status, runner_answer, _ = browser.fetch("/api/ask", {
            "model": runner_name, "prompt": "Reply OK."}, method="POST")
        _, listing, _ = browser.fetch("/api/models")
        runner_found = next((item for item in listing.get("models", [])
                             if item["id"] == runner_name), None)
        record("ADD-06", runner_status == 200 and runner_added.get("approved_classes") ==
               ["Public"] and runner_ask_status == 200 and
               bool(runner_answer.get("answer", "").strip()) and
               runner_found is not None and runner_found["approved"],
               {"add_http": runner_status, "ask_http": runner_ask_status,
                "answer_excerpt": runner_answer.get("answer", "")[:80],
                "approved": runner_found.get("approved") if runner_found else None})

        no_answer_status, no_answer, _ = browser.fetch("/api/models", {
            "name": bad_name, "model": "__keeplane_no_answer_trial__", "source": "fixture",
            "approved_classes": ["Public"]}, method="POST")
        resource_status, resources = gateway_call("GET", RESOURCE_PATH)
        list_status, listing, _ = browser.fetch("/api/models")
        record("ADD-07", no_answer_status == 503 and
               "Registration was removed" in no_answer.get("error", "") and
               resource_status == 200 and list_status == 200 and
               bad_name not in {item.get("id") for item in resources.get("resources", [])} and
               bad_name not in {item.get("id") for item in listing.get("models", [])},
               {"add_http": no_answer_status, "error": no_answer.get("error"),
                "gateway_http": resource_status, "list_http": list_status})
    finally:
        approval_status, _, _ = browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
        gateway_status, _ = gateway_call("DELETE", RESOURCE_PATH + "/" + name)
        runner_approval_status, _, _ = browser.fetch(f"/api/models/{runner_name}/setup", {}, method="DELETE")
        runner_gateway_status, _ = gateway_call("DELETE", RESOURCE_PATH + "/" + runner_name)
        gateway_call("DELETE", RESOURCE_PATH + "/" + bad_name)
        record("ADD-08", approval_status in (200, 404) and gateway_status in (200, 404) and
               runner_approval_status in (200, 404) and runner_gateway_status in (200, 404),
               {"approval_delete_http": approval_status, "gateway_delete_http": gateway_status,
                "runner_approval_delete_http": runner_approval_status,
                "runner_gateway_delete_http": runner_gateway_status})
        report = {"suite": "Spec 004 local model registration with approval",
                  "time_utc": datetime.now(timezone.utc).isoformat(), "cases": cases,
                  "passed": sum(item["verdict"] == "pass" for item in cases),
                  "failed": sum(item["verdict"] == "fail" for item in cases)}
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{report['passed']} passed, {report['failed']} failed; {REPORT}")
        for case in cases:
            print(case["id"], case["verdict"], case["observed"])
        if report["failed"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
