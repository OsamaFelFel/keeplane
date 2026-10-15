"""Live shared-key replacement regression against either protected preview."""

import json
import hashlib
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from reporting import report_path
from test_accounts import BASE, Browser, RUNTIME
from test_cloud_add import key_files, resource


REPORT = report_path("2026-10-09-key-rotation.json")


def main():
    fixture_file = RUNTIME / "cloud-provider-key"
    old_key = fixture_file.read_text().strip()
    new_key = secrets.token_urlsafe(32)
    baseline = key_files()
    name = "keeplane-rotate-" + uuid.uuid4().hex[:10]
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    cases = []
    cleanup_errors = []
    added = False

    def provider_key(value):
        if BASE == "http://127.0.0.1:3000":
            fixture_file.write_text(value + "\n")
            fixture_file.chmod(0o600)
            return
        if BASE != "http://127.0.0.1:13000":
            raise RuntimeError("Refusing key rotation against an unknown preview")
        prefix = ["kubectl", "--kubeconfig", os.environ.get(
            "KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")]
        context = subprocess.check_output(prefix + ["config", "current-context"], text=True).strip()
        if context != "kind-keeplane":
            raise RuntimeError("Refusing key rotation outside kind-keeplane")
        with tempfile.TemporaryDirectory(prefix="keeplane-kind-provider-key-") as directory:
            key_path = Path(directory) / "key"
            key_path.write_text(value + "\n")
            key_path.chmod(0o600)
            manifest = subprocess.run(prefix + ["-n", "keeplane", "create", "secret", "generic",
                                                "cloud-provider-key", "--from-file=key=" + str(key_path),
                                                "--dry-run=client", "-o", "yaml"],
                                      check=True, capture_output=True, text=True).stdout
            subprocess.run(prefix + ["-n", "keeplane", "apply", "-f", "-"], input=manifest,
                           check=True, capture_output=True, text=True)
        # The fixture reads this Secret file for every call. Updating it in
        # place avoids closing a connection that the gateway is using.
        expected_digest = hashlib.sha256(value.encode()).hexdigest()
        deadline = time.monotonic() + 120
        while True:
            pods = json.loads(subprocess.check_output(prefix + ["-n", "keeplane", "get",
                "pods", "-l", "app=cloud-provider", "-o", "json"], text=True))["items"]
            current = {pod["metadata"]["name"] for pod in pods
                       if not pod["metadata"].get("deletionTimestamp") and
                       any(condition.get("type") == "Ready" and condition.get("status") == "True"
                           for condition in pod["status"].get("conditions", []))}
            slices = json.loads(subprocess.check_output(prefix + ["-n", "keeplane", "get",
                "endpointslice", "-l", "kubernetes.io/service-name=cloud-provider",
                "-o", "json"], text=True))["items"]
            ready = {endpoint.get("targetRef", {}).get("name") for item in slices
                     for endpoint in item.get("endpoints", [])
                     if endpoint.get("conditions", {}).get("ready") is True}
            mounted_digest = subprocess.check_output(prefix + ["-n", "keeplane", "exec",
                "deployment/cloud-provider", "--", "python", "-c",
                "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('/run/provider-key/key').read_text().strip().encode()).hexdigest())"],
                text=True).strip()
            if len(current) == 1 and ready == current and mounted_digest == expected_digest:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Cloud provider Service or mounted key did not converge after rotation")
            time.sleep(0.3)

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    def item():
        status, result, _ = browser.fetch("/api/models")
        return status, next((entry for entry in result.get("models", []) if entry["id"] == name), None)

    def edit(classes, replacement=None):
        body = {"key_choice": "shared", "approved_classes": classes}
        if replacement is not None:
            body["replace_shared_key"] = replacement
        return browser.fetch(f"/api/models/{name}/setup", body, method="POST")[:2]

    try:
        status, _, _ = browser.fetch("/api/models", {
            "name": name, "model": "mock-rotate", "source": "openai",
            "key_choice": "shared", "shared_key": old_key,
            "approved_classes": ["Public"]}, method="POST")
        added = status == 200
        original_status, original_resource = resource(name)
        old_path = (original_resource or {}).get("auth", {}).get("key", {}).get("value", {}).get("file")
        original_files = key_files()

        invalid_status, _ = edit(["Internal"], "short")
        after_invalid_status, after_invalid = resource(name)
        record("ROT-01", status == 200 and invalid_status == 400 and
               original_status == after_invalid_status == 200 and
               after_invalid == original_resource and key_files() == original_files,
               {"add_status": status, "invalid_status": invalid_status,
                "gateway_unchanged": after_invalid == original_resource,
                "extra_key_files": len(key_files() - original_files)})

        wrong_status, _ = edit(["Internal"], "wrong-provider-key-" + uuid.uuid4().hex)
        after_wrong_status, after_wrong = resource(name)
        list_status, listed = item()
        ask_status, answer, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "Still there?"}, method="POST")
        record("ROT-02", wrong_status == 503 and after_wrong_status == list_status == 200 and
               after_wrong == original_resource and listed is not None and
               listed.get("approved_classes") == ["Public"] and
               ask_status == 200 and answer.get("answer") == "mock cloud answer" and
               key_files() == original_files,
               {"wrong_key_status": wrong_status, "gateway_unchanged": after_wrong == original_resource,
                "classes": listed.get("approved_classes") if listed else None,
                "old_answer_status": ask_status, "extra_key_files": len(key_files() - original_files)})

        empty_status, empty_result = edit(["Internal"], "")
        after_empty_status, after_empty = resource(name)
        empty_ask_status, _, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "Still there?"}, method="POST")
        record("ROT-03", empty_status == 200 and after_empty_status == 200 and
               after_empty == original_resource and empty_result.get("key_choice") == "shared" and
               empty_result.get("approved_classes") == ["Internal"] and empty_ask_status == 200 and
               key_files() == original_files,
               {"empty_key_status": empty_status, "gateway_unchanged": after_empty == original_resource,
                "classes": empty_result.get("approved_classes"), "answer_status": empty_ask_status})

        provider_key(new_key)
        replace_status, replace_result = edit(["Confidential"], new_key)
        new_resource_status, new_resource = resource(name)
        new_path = (new_resource or {}).get("auth", {}).get("key", {}).get("value", {}).get("file")
        new_ask_status, new_answer, _ = browser.fetch("/api/ask", {
            "model": name, "prompt": "New key?"}, method="POST")
        list_status, listed = item()
        files_after = key_files()
        record("ROT-04", replace_status == 200 and new_resource_status == list_status == 200 and
               replace_result.get("key_choice") == "shared" and
               listed is not None and listed.get("approved_classes") == ["Confidential"] and
               new_path and new_path != old_path and Path(new_path).name in files_after and
               Path(old_path).name not in files_after and len(files_after - baseline) == 1 and
               new_ask_status == 200 and new_answer.get("answer") == "mock cloud answer",
               {"replace_status": replace_status,
                "replace_error": replace_result.get("error", "")[:160],
                "classes": listed.get("approved_classes") if listed else None,
                "new_answer_status": new_ask_status,
                "old_file_removed": bool(old_path and Path(old_path).name not in files_after),
                "new_key_files": len(files_after - baseline)})

        remove_status, _, _ = browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
        if remove_status == 200:
            added = False
        final_resource_status, final_resource = resource(name)
        final_list_status, final_listed = item()
        record("ROT-05", remove_status == 200 and final_resource_status == final_list_status == 200 and
               final_resource is None and final_listed is None and key_files() == baseline,
               {"remove_status": remove_status,
                "gateway_entry": final_resource is not None,
                "listed": final_listed is not None,
                "extra_key_files": len(key_files() - baseline)})
    finally:
        if added:
            try:
                status, _, _ = browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
                if status != 200:
                    cleanup_errors.append(f"model removal returned HTTP {status}")
            except Exception as error:
                cleanup_errors.append(f"model removal raised {type(error).__name__}")
        try:
            provider_key(old_key)
        except Exception as error:
            cleanup_errors.append("provider key restore raised " + type(error).__name__)
        report = {"suite": "Protected preview shared-key replacement",
                  "time_utc": datetime.now(timezone.utc).isoformat(),
                  "gateway": "agentgateway local trial",
                  "provider_endpoint": "local authenticated mock",
                  "cases": cases,
                  "cleanup": "complete" if not cleanup_errors else cleanup_errors,
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
