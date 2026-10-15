"""Roll out the pinned upstream gateway chart with a Secret-backed URL placeholder."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get("KEEPLANE_NETPOL_KUBECONFIG", "/private/tmp/keeplane-netpol-kubeconfig")
HELM = os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or "/private/tmp/keeplane-helm/darwin-amd64/helm"
CHART = "deploy/helm/keeplane/charts/agentgateway-standalone-v1.6.0.tgz"
NAMESPACE = "keeplane-secret-" + uuid.uuid4().hex[:8]


def run(*command):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}: {result.stderr[-150:]}")
    return result.stdout.strip()


def kube(*args):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence output already exists")
    context = kube("config", "current-context")
    if context != "kind-keeplane-netpol":
        raise RuntimeError("Refusing a Kubernetes context other than kind-keeplane-netpol")
    rows = []
    created = False
    forwarded = None
    try:
        kube("create", "namespace", NAMESPACE)
        created = True
        kube("-n", NAMESPACE, "apply", "-f", "tests/e2e/gateway-secret/kind-db.yaml")
        kube("-n", NAMESPACE, "rollout", "status", "deployment/db", "--timeout=240s")
        kube("-n", NAMESPACE, "create", "secret", "generic", "gateway-db-credentials",
             "--from-literal=password=fixture-only")
        run(HELM, "--kubeconfig", KUBECONFIG, "install", "gateway", CHART,
            "--namespace", NAMESPACE, "-f", "tests/e2e/gateway-secret/upstream-values.yaml",
            "--wait", "--timeout", "240s")
        deployment = json.loads(kube("-n", NAMESPACE, "get", "deployment", "gateway", "-o", "json"))
        configmap = json.loads(kube("-n", NAMESPACE, "get", "configmap", "gateway-config", "-o", "json"))
        config_data = "\n".join(configmap["data"].values())
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        secret_env = any(item.get("name") == "TRIAL_DB_PASSWORD" and
                         item.get("valueFrom", {}).get("secretKeyRef", {}) ==
                         {"name": "gateway-db-credentials", "key": "password"} for item in env)
        replicas_ready = deployment["status"].get("readyReplicas", 0)
        port = free_port()
        forwarded = subprocess.Popen(
            ("kubectl", "--kubeconfig", KUBECONFIG, "-n", NAMESPACE, "port-forward",
             "deployment/gateway", f"{port}:15021"), cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if forwarded.poll() is not None:
                raise RuntimeError("gateway health port-forward exited early")
            try:
                status = urlopen(f"http://127.0.0.1:{port}/healthz/ready", timeout=2).status
                break
            except Exception:
                time.sleep(0.3)
        rows.append({"case": "GSECRET-04", "verdict": "pass" if
                     (replicas_ready == 1 and status == 200 and secret_env
                      and "${TRIAL_DB_PASSWORD}" in config_data
                      and "fixture-only" not in config_data) else "fail",
                     "observed": {"ready_replicas": replicas_ready, "health_http_status": status,
                                  "secret_reference": secret_env,
                                  "placeholder_in_configmap": "${TRIAL_DB_PASSWORD}" in config_data,
                                  "password_in_configmap": "fixture-only" in config_data}})
    except Exception as error:
        rows.append({"case": "GSECRET-TRIAL", "verdict": "fail",
                     "observed": {"error": type(error).__name__, "detail": str(error)[:250]}})
    finally:
        if forwarded:
            forwarded.terminate()
            try:
                forwarded.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forwarded.kill()
        if created:
            kube("delete", "namespace", NAMESPACE, "--wait=true")
    report = {"suite": "isolated Kubernetes gateway database Secret", "context": context,
              "namespace_removed": created, "results": rows, "release_package_approved": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(len(rows) != 1 or rows[0]["verdict"] == "fail")


if __name__ == "__main__":
    sys.exit(main())
