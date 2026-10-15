"""Exercise the protected app against a separately managed gateway in kind."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from kind_port_forward import BASE, KUBECONFIG, existing_app
from reporting import report_path
from test_accounts import Browser, RUNTIME


ROOT = Path(__file__).resolve().parents[2]
REPORT = report_path("2026-10-10-protected-existing-live.json")


def case(identifier, passed, observed):
    return {"case": identifier, "verdict": "pass" if passed else "fail",
            "observed": observed}


def provider_key_files():
    names = subprocess.check_output(
        ["kubectl", "--kubeconfig", KUBECONFIG, "-n", "keeplane-existing",
         "exec", "deployment/keeplane-existing-app", "--", "python", "-c",
         "import json,pathlib;print(json.dumps(sorted(p.name for p in pathlib.Path('/provider-keys').glob('key-*'))))"],
        text=True, timeout=30)
    return json.loads(names)


def main():
    if REPORT.exists():
        raise RuntimeError("Live evidence already exists; choose a new run filename")
    rows = []
    with existing_app(), tempfile.TemporaryDirectory(prefix="keeplane-existing-accounts-") as temporary:
        environment = os.environ.copy()
        environment["KEEPLANE_BASE_URL"] = BASE
        environment["KEEPLANE_TEST_REPORT_DIR"] = temporary
        accounts = subprocess.run([sys.executable, "tests/e2e/test_accounts.py"],
                                  cwd=ROOT, env=environment, capture_output=True,
                                  text=True, timeout=180)
        account_report = Path(temporary) / "2026-10-10-users-react.json"
        account_cases = json.loads(account_report.read_text())["cases"] if account_report.exists() else []
        rows.append(case("EXIST-01", accounts.returncode == 0 and
                         len(account_cases) == 21 and
                         all(item["verdict"] == "pass" for item in account_cases),
                         {"account_case_count": len(account_cases),
                          "account_passed": sum(item["verdict"] == "pass" for item in account_cases),
                          "account_cases": [{"id": item["id"], "verdict": item["verdict"]}
                                            for item in account_cases],
                          "account_exit": accounts.returncode}))

        anonymous_status, _, _ = Browser(BASE).fetch("/api/models")
        admin = Browser(BASE)
        login_status = admin.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())[0]
        models_status, models, _ = admin.fetch("/api/models")
        class_status, classes, _ = admin.fetch("/api/data-classes")
        audit_status, audit, _ = admin.fetch("/api/audit/options")
        model_rows = {item["id"]: item for item in (models or {}).get("models", [])}
        rows.append(case("EXIST-02", anonymous_status == 401 and login_status == 200 and
                         models_status == class_status == audit_status == 200 and
                         "customer-fixture" in model_rows and "customer-managed" in model_rows and
                         (classes or {}).get("enabled") is False and
                         set((audit or {}).get("options", {})) ==
                         {"settings", "held_requests", "model_answers"},
                         {"anonymous_status": anonymous_status, "login_status": login_status,
                          "models_status": models_status, "model_names": sorted(model_rows),
                          "classes_status": class_status, "classes_enabled": (classes or {}).get("enabled"),
                          "audit_status": audit_status}))

        approved_status, approved, _ = admin.fetch("/api/ask", {
            "model": "customer-managed", "prompt": "fixture"}, method="POST")
        outside_status, _, _ = admin.fetch("/api/ask", {
            "model": "customer-fixture", "prompt": "fixture"}, method="POST")
        rows.append(case("EXIST-03", approved_status == 200 and
                         (approved or {}).get("answer") == "mock answer" and outside_status == 403,
                         {"approved_status": approved_status, "approved_answer":
                          (approved or {}).get("answer"), "outside_status": outside_status}))

        before_files = provider_key_files()
        before_models = sorted(model_rows)
        proposed = "unsupported-shared-" + uuid.uuid4().hex[:10]
        rejected_status, rejected, _ = admin.fetch("/api/models", {
            "name": proposed, "model": "mock-cloud", "source": "openai",
            "key_choice": "shared", "shared_key": "disposable-fixture-key",
            "approved_classes": []}, method="POST")
        after_status, after, _ = admin.fetch("/api/models")
        after_models = sorted(item["id"] for item in (after or {}).get("models", []))
        after_files = provider_key_files()
        still_answers, _, _ = admin.fetch("/api/ask", {
            "model": "customer-managed", "prompt": "fixture"}, method="POST")
        rows.append(case("EXIST-04", rejected_status == 422 and
                         "delivery path" in (rejected or {}).get("error", "") and
                         after_status == 200 and proposed not in after_models and
                         before_models == after_models and before_files == after_files and
                         still_answers == 200,
                         {"rejected_status": rejected_status, "gateway_catalog_unchanged":
                          before_models == after_models, "key_files_unchanged":
                          before_files == after_files, "existing_answer_status": still_answers}))

    report = {"suite": "Protected existing-gateway local trial", "cases": rows,
              "passed": sum(row["verdict"] == "pass" for row in rows),
              "failed": sum(row["verdict"] == "fail" for row in rows)}
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(report["failed"] > 0)


if __name__ == "__main__":
    sys.exit(main())
