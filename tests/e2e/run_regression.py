"""Run the documented local suites and save one fresh, reviewable result."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from test_accounts import Browser, RUNTIME
from protected_preview import login_if_protected


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Suite:
    name: str
    command: tuple
    case_ids: str
    report: str = ""
    environment: tuple = ()
    stdin: str = ""
    needs_stack: bool = True
    timeout: int = 420


def py(name, *args):
    return (sys.executable, "tests/e2e/test_" + name + ".py", *args)


SUITES = (
    Suite("chart-package", py("chart_package"), "PKG-01 PKG-02 PKG-03 PKG-04", needs_stack=False),
    Suite("catalog-store", py("model_catalog"), "catalog-store", needs_stack=False),
    Suite("data-class-store", py("data_classes_store"), "data-class-store", needs_stack=False),
    Suite("audit-store", py("audit_store"), "audit-store", needs_stack=False),
    Suite("management-retry", py("management_retry"), "MGMT-01 MGMT-02 MGMT-03",
          environment=(("PYTHONPATH", "components/control-plane"),), needs_stack=False),
    Suite("existing-preflight-read-retry", py("gateway_preflight_read_retry"), "K8S-14 K8S-15 K8S-16",
          environment=(("PYTHONPATH", "components/control-plane"),), needs_stack=False),
    Suite("local-identity", py("local_identity"), "ACCT-21 ACCT-22", needs_stack=False),
    Suite("break-glass-store", py("break_glass_audit_store"),
          "BG-01 BG-02 BG-03 BG-04 BG-05 BG-06", needs_stack=False),
    Suite("stack-lock", py("stack_lock"), "LOCK-01 LOCK-02 LOCK-03 LOCK-04 LOCK-05"),
    Suite("docker-local", py("local"), "LOCAL-01 LOCAL-02 LOCAL-03 LOCAL-04 LOCAL-05 LOCAL-08 LOCAL-11",
          environment=(("KEEPLANE_BASE_URL", "http://127.0.0.1:3000"),)),
    Suite("kind-local", py("local"), "LOCAL-01 LOCAL-02 LOCAL-03 LOCAL-04 LOCAL-05 LOCAL-08 LOCAL-11",
          environment=(("KEEPLANE_BASE_URL", "http://127.0.0.1:13000"),)),
    Suite("docker-qwen", py("qwen"), "LOCAL-07 LOCAL-09",
          environment=(("KEEPLANE_BASE_URL", "http://127.0.0.1:3000"),)),
    Suite("kind-qwen", py("qwen"), "LOCAL-07 LOCAL-09",
          environment=(("KEEPLANE_BASE_URL", "http://127.0.0.1:13000"),)),
    Suite("guarded-endpoint", ("docker", "compose", "exec", "-T", "app", "python", "-"),
          "LOCAL-12 LOCAL-13 LOCAL-14 LOCAL-15", stdin="tests/e2e/test_guarded_endpoint.py"),
    Suite("docker-runner", py("runner_flow"), "LOCAL-23 LOCAL-21 LOCAL-24 LOCAL-21-ADD LOCAL-22",
          environment=(("KEEPLANE_BASE_URL", "http://127.0.0.1:3000"),)),
    Suite("kind-runner", py("runner_flow"), "LOCAL-23 LOCAL-21 LOCAL-24 LOCAL-21-ADD LOCAL-22",
          environment=(("KEEPLANE_BASE_URL", "http://127.0.0.1:13000"),)),
    Suite("kind-failover", py("kind"), "K8S-01 K8S-02 K8S-03 K8S-04 K8S-07 K8S-05 K8S-06"),
    Suite("kind-gateway-down", py("gateway_down"), "K8S-08 K8S-09", timeout=240),
    Suite("kind-existing-preflight", py("existing_gateway_preflight"), "K8S-10 K8S-11 K8S-12 K8S-13", timeout=240),
    Suite("accounts", py("accounts"),
          "ACCT-01 ACCT-02 ACCT-03 ACCT-04 ACCT-05 ACCT-06 ACCT-07 ACCT-08 ACCT-09 ACCT-10 ACCT-11 ACCT-12 ACCT-13 ACCT-14 ACCT-15 ACCT-16 ACCT-17 ACCT-18 ACCT-19 ACCT-20 ACCT-23",
          report="2026-10-10-users-react.json"),
    Suite("data-classes", py("data_classes"),
          "CLASS-00 CLASS-10 CLASS-01 CLASS-09 CLASS-02 CLASS-03 CLASS-04 CLASS-05 CLASS-06 CLASS-08 CLASS-07",
          report="2026-10-09-data-classes.json"),
    Suite("model-approval", py("model_approval"),
          "MODEL-01 MODEL-02 MODEL-03 MODEL-10 MODEL-04 MODEL-05 MODEL-06 MODEL-07 MODEL-08 MODEL-09",
          report="2026-10-09-model-approval.json"),
    Suite("model-edit", py("model_edit"), "EDIT-01 EDIT-02 EDIT-03 EDIT-04 EDIT-05",
          report="2026-10-09-model-edit.json"),
    Suite("model-replacement", py("model_replacement"),
          "REPLACE-01 REPLACE-02 REPLACE-03 REPLACE-04 REPLACE-05",
          report="2026-10-09-model-replacement.json"),
    Suite("audit", py("audit"),
          "AUD-01 AUD-02 AUD-05 AUD-03 AUD-04 AUD-06 AUD-08 AUD-09 AUD-07",
          report="2026-10-10-audit-developer.json"),
    Suite("break-glass-audit", py("break_glass_audit"), "BG-07 BG-08 BG-09",
          report="2026-10-10-break-glass-audit.json"),
    Suite("model-add", py("model_add"), "ADD-01 ADD-02 ADD-03 ADD-04 ADD-05 ADD-06 ADD-07 ADD-08",
          report="2026-10-09-model-add.json"),
    Suite("cloud-listing", py("cloud_listing"), "CLOUD-01 CLOUD-02 CLOUD-03 CLOUD-04",
          report="2026-10-09-cloud-listing.json"),
    Suite("cloud-add", py("cloud_add"),
          "CADD-01 CADD-02 CADD-03 CADD-04 CADD-05 CADD-06 CADD-07 CADD-08 CADD-09",
          report="2026-10-09-cloud-add.json"),
    Suite("key-rotation", py("key_rotation"),
          "ROT-01 ROT-02 ROT-03 ROT-04 ROT-05",
          report="2026-10-09-key-rotation.json"),
    Suite("model-removal", py("model_removal"),
          "REMOVE-01 REMOVE-02 REMOVE-03 REMOVE-04 REMOVE-05 REMOVE-06 REMOVE-07",
          report="2026-10-09-model-removal.json"),
    Suite("docker-runtime", py("model_runtime", "--docker"), "LOCAL-19 LOCAL-20"),
    Suite("kind-runtime", py("model_runtime", "--kind"), "LOCAL-19 LOCAL-20"),
    Suite("integrated-demo", py("integrated_demo"),
          "DEMO-01 DEMO-02 DEMO-03 DEMO-04 DEMO-05 DEMO-06",
          report="2026-10-09-integrated-demo.json"),
)


def git(*args):
    return subprocess.check_output(("git", *args), cwd=ROOT, text=True).strip()


def preflight():
    kubeconfig = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")
    context = subprocess.check_output(("kubectl", "--kubeconfig", kubeconfig,
                                       "config", "current-context"), text=True).strip()
    if context != "kind-keeplane":
        raise RuntimeError("The isolated kind-keeplane context is required")
    browser = Browser()
    login_status, _, _, _, _ = browser.login(
        "first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    docker_status, docker_health, _ = browser.fetch("/health")
    if login_status != 200 or docker_status != 200 or docker_health.get("gateway") != "ready":
        raise RuntimeError("Protected Docker preview or gateway is not healthy")
    login_if_protected("http://127.0.0.1:13000")
    with urlopen("http://127.0.0.1:13000/health", timeout=10) as response:
        if response.status != 200 or json.load(response).get("gateway") != "ready":
            raise RuntimeError("Isolated kind preview or gateway is not healthy")
    mode_status, settings, _ = browser.fetch("/api/data-classes")
    if mode_status != 200:
        raise RuntimeError("Could not read the Data Classes mode")
    initial_mode = settings["enabled"]
    if not initial_mode:
        changed, _, _ = browser.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")
        if changed != 200:
            raise RuntimeError("Could not enable classes for the older class-dependent suites")
    return browser, initial_mode


def case_rows(suite, stdout, report_dir, exit_code):
    if suite.report:
        path = report_dir / suite.report
        if not path.is_file():
            raise ValueError("Suite did not write a fresh report")
        source = json.loads(path.read_text())
        rows = source["cases"]
    elif suite.name in ("catalog-store", "data-class-store", "audit-store"):
        rows = [{"id": suite.case_ids, "verdict": "pass" if exit_code == 0 else "fail"}]
    else:
        source = json.loads(stdout)
        rows = source["results"]
    return [{"id": row.get("id", row.get("case")), "verdict": row["verdict"],
             **({"observed": row.get("observed")} if row["verdict"] != "pass" else {})}
            for row in rows]


def run_suite(suite, report_dir):
    env = os.environ.copy()
    env["KEEPLANE_TEST_REPORT_DIR"] = str(report_dir)
    env.update(suite.environment)
    input_text = (ROOT / suite.stdin).read_text() if suite.stdin else None
    started = time.monotonic()
    try:
        process = subprocess.run(suite.command, cwd=ROOT, env=env, input=input_text,
                                 capture_output=True, text=True, timeout=suite.timeout)
        exit_code, stdout = process.returncode, process.stdout
        execution_error = ""
    except subprocess.TimeoutExpired:
        exit_code, stdout = None, ""
        execution_error = "Suite timed out after %d seconds" % suite.timeout
    try:
        rows = case_rows(suite, stdout, report_dir, exit_code)
        expected = suite.case_ids.split()
        actual = [row["id"] for row in rows]
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        complete = len(actual) == len(expected) and not missing and not extra
        parsing_error = ""
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        rows, missing, extra, complete = [], suite.case_ids.split(), [], False
        parsing_error = type(error).__name__ + ": " + str(error)
    passed = exit_code == 0 and complete and all(row["verdict"] == "pass" for row in rows)
    result = {"suite": suite.name, "command": suite.command,
              "environment": dict(suite.environment), "exit_code": exit_code,
              "duration_seconds": round(time.monotonic() - started, 1),
              "cases": rows, "expected_case_count": len(suite.case_ids.split()),
              "passed": passed}
    if missing or extra:
        result["case_mismatch"] = {"missing": missing, "extra": extra}
    if parsing_error or execution_error:
        result["error"] = execution_error or parsing_error
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New JSON evidence file; existing files are never overwritten")
    parser.add_argument("--suite", action="append", choices=[suite.name for suite in SUITES],
                        help="Run selected suite(s); omit for all suites")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Output exists; choose a new evidence filename")
    selected = [suite for suite in SUITES if not args.suite or suite.name in args.suite]
    mode_browser, initial_mode = preflight() if any(suite.needs_stack for suite in selected) else (None, None)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"started_utc": datetime.now(timezone.utc).isoformat(),
              "git_head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
              "working_tree_dirty": bool(git("status", "--porcelain")),
              "stack_lock_sha256": hashlib.sha256((ROOT / "deploy/local/stack.lock.json").read_bytes()).hexdigest(),
              "selected_suites": [suite.name for suite in selected],
              "completed": False, "results": []}
    try:
        with tempfile.TemporaryDirectory(prefix="keeplane-regression-") as temp:
            report_dir = Path(temp)
            for suite in selected:
                item = run_suite(suite, report_dir)
                result["results"].append(item)
                output.write_text(json.dumps(result, indent=2) + "\n")
                print(suite.name + ": " + ("PASS" if item["passed"] else "FAIL") +
                      " (%d cases, %.1fs)" % (len(item["cases"]), item["duration_seconds"]), flush=True)
    finally:
        if mode_browser is not None:
            restored, _, _ = mode_browser.fetch("/api/data-classes/mode",
                                                {"enabled": initial_mode}, method="PUT")
            result["data_classes_mode_restored"] = restored == 200
            result["data_classes_initial_mode"] = initial_mode
    result["completed"] = True
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["suites_passed"] = sum(item["passed"] for item in result["results"])
    result["suites_total"] = len(selected)
    result["cases_reported"] = sum(len(item["cases"]) for item in result["results"])
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("%d/%d suites passed; %d case records; %s" %
          (result["suites_passed"], result["suites_total"], result["cases_reported"], output))
    return int(result["suites_passed"] != result["suites_total"] or
               result.get("data_classes_mode_restored") is False)


if __name__ == "__main__":
    sys.exit(main())
