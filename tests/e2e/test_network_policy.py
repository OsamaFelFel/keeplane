"""Exercise the rendered managed-gateway NetworkPolicy on isolated Calico kind."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get("KEEPLANE_NETPOL_KUBECONFIG", "/private/tmp/keeplane-netpol-kubeconfig")
HELM = os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or "/private/tmp/keeplane-helm/darwin-amd64/helm"
NAMESPACE = "keeplane-netpol-" + uuid.uuid4().hex[:8]
PROBE = '''import urllib.request
try:
 with urllib.request.urlopen("http://gateway:4000/",timeout=3) as response:
  print(response.status)
except Exception as error:
 print("blocked:"+type(error).__name__)'''


def run(*command, input_text=None):
    result = subprocess.run(command, cwd=ROOT, text=True, input=input_text,
                            capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-300:]}")
    return result.stdout.strip()


def kube(*args, input_text=None):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args, input_text=input_text)


def probe(pod):
    return kube("-n", NAMESPACE, "exec", "pod/" + pod, "--", "python", "-c", PROBE)


def wait_for(expected_app, expected_sibling, seconds=30):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        last = {"app": probe("keeplane-app"), "sibling": probe("sibling")}
        if last["app"] == expected_app and (
                last["sibling"] == expected_sibling if expected_sibling == "200"
                else last["sibling"].startswith("blocked:")):
            return last
        time.sleep(1)
    return last


def case(identifier, passed, observed):
    return {"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed}


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
    try:
        kube("create", "namespace", NAMESPACE)
        created = True
        kube("-n", NAMESPACE, "apply", "-f", "tests/e2e/network-policy/workloads.yaml")
        kube("-n", NAMESPACE, "wait", "--for=condition=Ready", "pod", "--all", "--timeout=240s")
        before = wait_for("200", "200")
        rows.append(case("NET-01", before == {"app": "200", "sibling": "200"}, before))
        manifest = run(HELM, "template", "keeplane", "deploy/helm/keeplane", "-f",
                       "deploy/local/values.yaml", "--set", "networkPolicy.gatewayIngressEnabled=true",
                       "--show-only", "templates/gateway-networkpolicy.yaml")
        kube("-n", NAMESPACE, "apply", "-f", "-", input_text=manifest)
        protected = wait_for("200", "blocked")
        rows.append(case("NET-02", protected["app"] == "200" and
                         protected["sibling"].startswith("blocked:"), protected))
        kube("-n", NAMESPACE, "label", "pod/sibling", "app=keeplane-app", "--overwrite")
        spoofed = wait_for("200", "200")
        rows.append(case("NET-03", spoofed == {"app": "200", "sibling": "200"}, spoofed))
        kube("-n", NAMESPACE, "label", "pod/sibling", "app-")
        isolated_again = wait_for("200", "blocked")
        rows.append(case("NET-04", isolated_again["app"] == "200" and
                         isolated_again["sibling"].startswith("blocked:"), isolated_again))
        kube("-n", NAMESPACE, "delete", "networkpolicy", "keeplane-gateway-ingress")
        restored = wait_for("200", "200")
        rows.append(case("NET-05", restored == {"app": "200", "sibling": "200"}, restored))
    except Exception as error:
        rows.append(case("NET-TRIAL", False, {"error": type(error).__name__, "detail": str(error)[:300]}))
    finally:
        if created:
            kube("delete", "namespace", NAMESPACE, "--wait=true")
    report = {"suite": "isolated enforcing-CNI gateway ingress", "context": context,
              "namespace_removed": created, "results": rows, "production_network_boundary_proved": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(len(rows) != 5 or any(row["verdict"] == "fail" for row in rows))


if __name__ == "__main__":
    sys.exit(main())
