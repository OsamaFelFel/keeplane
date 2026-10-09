"""Live cloud registration and key lifecycle trial; reports no key values."""

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from reporting import report_path
from test_accounts import Browser, RUNTIME
from test_model_replacement import gateway_call


REPORT = report_path("2026-10-09-cloud-add.json")
RESOURCE_PATH = "/api/config/resources/llm.model"
CONTAINER = "keeplane-local-app-1"


def key_files():
    script = "import json, pathlib; print(json.dumps(sorted(p.name for p in pathlib.Path('/provider-keys').glob('key-*'))))"
    result = subprocess.run(["docker", "exec", CONTAINER, "python", "-c", script],
                            check=True, capture_output=True, text=True, timeout=15)
    return set(json.loads(result.stdout))


def key_metadata(path):
    script = "import json, os, sys; s=os.stat(sys.argv[1]); print(json.dumps({'uid':s.st_uid,'mode':oct(s.st_mode & 0o777)}))"
    result = subprocess.run(["docker", "exec", CONTAINER, "python", "-c", script, path],
                            check=True, capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)


def resource(name):
    status, result = gateway_call("GET", RESOURCE_PATH)
    if status != 200:
        return status, None
    return status, next((item["value"] for item in result.get("resources", [])
                         if item.get("id") == name), None)


def main():
    key = (RUNTIME / "cloud-provider-key").read_text().strip()
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    anonymous = Browser()
    suffix = uuid.uuid4().hex[:10]
    openai_name = "keeplane-openai-" + suffix
    anthropic_name = "keeplane-anthropic-" + suffix
    wrong_name = "keeplane-wrong-" + suffix
    baseline = key_files()
    cases = []
    cleanup_errors = []
    added = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def add(name, source, upstream, provider_key, classes=None):
        return browser.fetch("/api/models", {"name": name, "model": upstream,
            "source": source, "key_choice": "shared", "shared_key": provider_key,
            "approved_classes": classes or ["Public"]}, method="POST")[:2]

    try:
        anonymous_status, _, _ = anonymous.fetch("/api/models", {
            "name": wrong_name, "model": "mock-cloud", "source": "openai",
            "key_choice": "shared", "shared_key": key,
            "approved_classes": ["Public"]}, method="POST")
        status, absent = resource(wrong_name)
        record("CADD-01", anonymous_status == 401 and status == 200 and absent is None,
               {"anonymous_status": anonymous_status, "gateway_entry": absent is not None})

        add_status, add_result = add(openai_name, "openai", "mock-cloud", key)
        if add_status == 200:
            added.append(openai_name)
        ask_status, answer, _ = browser.fetch("/api/ask", {
            "model": openai_name, "prompt": "Say hello"}, method="POST")
        list_status, listing, _ = browser.fetch("/api/models")
        listed = next((item for item in listing.get("models", []) if item["id"] == openai_name), None)
        record("CADD-02", add_status == 200 and ask_status == 200 and
               answer.get("answer") == "mock cloud answer" and list_status == 200 and
               listed is not None and listed.get("provider") == "OpenAI" and
               listed.get("kind") == "cloud" and listed.get("approved") and
               listed.get("key_choice") == "shared" and
               listed.get("approved_classes") == ["Public"],
               {"add_status": add_status, "ask_status": ask_status,
                "listed_provider": listed.get("provider") if listed else None,
                "listed_key_choice": listed.get("key_choice") if listed else None})

        resource_status, openai_resource = resource(openai_name)
        file_path = (openai_resource or {}).get("auth", {}).get("key", {}).get("value", {}).get("file")
        metadata = key_metadata(file_path) if file_path else {}
        after_openai = key_files()
        no_key = key not in json.dumps(add_result) and key not in json.dumps(listing) and \
            key not in json.dumps(openai_resource)
        record("CADD-03", resource_status == 200 and no_key and file_path and
               file_path.startswith("/provider-keys/key-") and
               metadata == {"uid": 65532, "mode": "0o600"} and
               len(after_openai - baseline) == 1,
               {"resource_status": resource_status, "key_absent_from_api": no_key,
                "file_reference_only": bool(file_path), "key_file_metadata": metadata,
                "new_key_files": len(after_openai - baseline)})

        duplicate_status, _, = add("another-" + openai_name, "openai", "mock-cloud", key)
        duplicate_resource_status, duplicate_resource = resource("another-" + openai_name)
        record("CADD-04", duplicate_status == 409 and duplicate_resource_status == 200 and
               duplicate_resource is None and key_files() == after_openai,
               {"duplicate_status": duplicate_status,
                "duplicate_gateway_entry": duplicate_resource is not None,
                "extra_key_files": len(key_files() - after_openai)})

        wrong_status, _ = add(wrong_name, "openai", "mock-wrong", "wrong-provider-key-" + suffix,
                              ["Public"])
        wrong_resource_status, wrong_resource = resource(wrong_name)
        wrong_list_status, wrong_listing, _ = browser.fetch("/api/models")
        wrong_listed = next((item for item in wrong_listing.get("models", [])
                             if item["id"] == wrong_name), None)
        record("CADD-05", wrong_status == 503 and wrong_resource_status == 200 and
               wrong_resource is None and wrong_list_status == 200 and
               wrong_listed is None and key_files() == after_openai,
               {"wrong_key_status": wrong_status, "gateway_entry": wrong_resource is not None,
                "listed": wrong_listed is not None,
                "extra_key_files": len(key_files() - after_openai)})

        anth_status, _ = add(anthropic_name, "anthropic", "mock-claude", key)
        if anth_status == 200:
            added.append(anthropic_name)
        anth_ask_status, anth_answer, _ = browser.fetch("/api/ask", {
            "model": anthropic_name, "prompt": "Say hello"}, method="POST")
        anth_list_status, anth_listing, _ = browser.fetch("/api/models")
        anth_listed = next((item for item in anth_listing.get("models", [])
                            if item["id"] == anthropic_name), None)
        record("CADD-06", anth_status == 200 and anth_ask_status == 200 and
               anth_answer.get("answer") == "mock cloud answer" and
               anth_list_status == 200 and anth_listed is not None and
               anth_listed.get("provider") == "Anthropic" and
               anth_listed.get("approved_classes") == ["Public"],
               {"add_status": anth_status, "ask_status": anth_ask_status,
                "listed_provider": anth_listed.get("provider") if anth_listed else None})

        edit_status, edited, _ = browser.fetch(f"/api/models/{openai_name}/setup", {
            "key_choice": "shared", "approved_classes": ["Internal"]}, method="POST")
        after_edit_status, after_edit, _ = browser.fetch("/api/models")
        edited_item = next((item for item in after_edit.get("models", [])
                            if item["id"] == openai_name), None)
        edited_ask_status, _, _ = browser.fetch("/api/ask", {
            "model": openai_name, "prompt": "Say hello"}, method="POST")
        record("CADD-07", edit_status == 200 and edited.get("key_choice") == "shared" and
               after_edit_status == 200 and edited_item is not None and
               edited_item.get("approved_classes") == ["Internal"] and
               edited_ask_status == 200,
               {"edit_status": edit_status,
                "key_choice": edited.get("key_choice"),
                "classes": edited_item.get("approved_classes") if edited_item else None,
                "ask_status": edited_ask_status})

        invalid_name = "keeplane-invalid-" + suffix
        invalid_status, _, = add(invalid_name, "openai", "mock-invalid", key,
                                 ["Unknown trial class"])
        invalid_resource_status, invalid_resource = resource(invalid_name)
        record("CADD-08", invalid_status == 400 and invalid_resource_status == 200 and
               invalid_resource is None and len(key_files() - baseline) == 2,
               {"invalid_class_status": invalid_status,
                "gateway_entry": invalid_resource is not None,
                "new_key_files": len(key_files() - baseline)})

        removed_statuses = []
        for name in (openai_name, anthropic_name):
            status, _, _ = browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
            removed_statuses.append(status)
            if status == 200:
                added.remove(name)
        openai_resource_status, openai_after = resource(openai_name)
        anth_resource_status, anth_after = resource(anthropic_name)
        record("CADD-09", removed_statuses == [200, 200] and
               openai_resource_status == anth_resource_status == 200 and
               openai_after is None and anth_after is None and key_files() == baseline,
               {"remove_statuses": removed_statuses,
                "gateway_entries_remaining": sum(item is not None for item in (openai_after, anth_after)),
                "key_files_after_cleanup": len(key_files() - baseline)})
    finally:
        for name in added:
            try:
                status, _, _ = browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
                if status != 200:
                    cleanup_errors.append(f"{name}: HTTP {status}")
            except Exception as error:
                cleanup_errors.append(f"{name}: {type(error).__name__}")
        report = {"suite": "Protected Docker cloud model registration",
                  "time_utc": datetime.now(timezone.utc).isoformat(),
                  "gateway": "agentgateway local trial",
                  "provider_endpoint": "local authenticated mock",
                  "cases": cases, "cleanup": "complete" if not cleanup_errors else cleanup_errors,
                  "passed": sum(case["verdict"] == "pass" for case in cases),
                  "failed": sum(case["verdict"] == "fail" for case in cases)}
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{report['passed']} passed, {report['failed']} failed; cleanup {report['cleanup']}; {REPORT}")
        for case in cases:
            print(case["id"], case["verdict"], case["observed"])
        if report["failed"] or cleanup_errors:
            sys.exit(1)


if __name__ == "__main__":
    main()
