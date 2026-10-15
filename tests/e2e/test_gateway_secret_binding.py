"""Prove pinned gateway database URL environment expansion and chart Secret wiring."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = "tests/e2e/gateway-secret/compose.yaml"
CONFIG = ROOT / "tests/e2e/gateway-secret/config.yaml"
HELM = os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or "/private/tmp/keeplane-helm/darwin-amd64/helm"
PYTHON = "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"
GATEWAY = "cr.agentgateway.dev/agentgateway@sha256:9d3e6044ddcdc0878b1787f77bd401252b95e22684203fb5e874c4c42d2ed90c"


def run(*command, check=True):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=150)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}")
    return result


def row(identifier, passed, observed):
    return {"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence output already exists")
    project = "keeplane-secret-" + uuid.uuid4().hex[:8]
    wrong = project + "-wrong"
    compose = ("docker", "compose", "-f", COMPOSE, "-p", project)
    cases = []
    try:
        run(*compose, "up", "-d", "--wait")
        ready = run("docker", "run", "--rm", "--network", project + "_default",
                    PYTHON, "python", "-c", "import urllib.request; "
                    "print(urllib.request.urlopen('http://gateway:15021/healthz/ready',timeout=5).status)")
        cases.append(row("GSECRET-01", ready.stdout.strip() == "200",
                         {"ready_http_status": int(ready.stdout.strip())}))
        run("docker", "run", "-d", "--name", wrong, "--network", project + "_default",
            "-e", "TRIAL_DB_PASSWORD=wrong", "-v", str(CONFIG) + ":/config.yaml:ro",
            GATEWAY, "-f", "/config.yaml")
        exit_code = int(run("docker", "wait", wrong).stdout.strip())
        logs = run("docker", "logs", wrong, check=False)
        auth_failed = "password authentication failed" in logs.stdout + logs.stderr
        cases.append(row("GSECRET-02", exit_code != 0 and auth_failed,
                         {"wrong_password_exit": exit_code, "authentication_failed": auth_failed}))
        render = run(HELM, "template", "keeplane", "deploy/helm/keeplane", "-f",
                     "deploy/local/values.yaml", "-f", "tests/e2e/gateway-secret/values.yaml")
        parts = render.stdout.split("---\n")
        config = next((part for part in parts if "kind: ConfigMap\n" in part
                       and "name: keeplane-config\n" in part), "")
        deployment = next((part for part in parts if "kind: Deployment\n" in part
                           and "name: keeplane\n" in part), "")
        placeholder = "${TRIAL_DB_PASSWORD}" in config
        password_visible = "fixture-only" in config
        secret_ref = ("name: TRIAL_DB_PASSWORD" in deployment
                      and "name: gateway-db-credentials" in deployment
                      and "key: password" in deployment)
        cases.append(row("GSECRET-03", placeholder and not password_visible and secret_ref,
                         {"placeholder_in_configmap": placeholder,
                          "fixture_password_in_configmap": password_visible,
                          "deployment_secret_reference": secret_ref}))
    except Exception as error:
        cases.append(row("GSECRET-TRIAL", False,
                         {"error": type(error).__name__, "detail": str(error)[:180]}))
    finally:
        run("docker", "rm", "-f", wrong, check=False)
        run(*compose, "down", "--volumes", "--remove-orphans", check=False)
    report = {"suite": "pinned gateway Secret binding", "cases": cases,
              "release_package_approved": False, "disposable_project_removed": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(len(cases) != 3 or any(case["verdict"] == "fail" for case in cases))


if __name__ == "__main__":
    sys.exit(main())
