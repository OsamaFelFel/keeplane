"""Keep the admin UI reachable while an existing gateway is unavailable in kind."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")
HELM = (os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or
        "/private/tmp/keeplane-helm/darwin-amd64/helm")
NAMESPACE = "keeplane-gateway-down-" + str(os.getpid())
RELEASE = "keeplane-down"


def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.PIPE).strip()


def kubectl(*args):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args)


def record(identifier, passed, observed):
    return {"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed}


def main():
    context = kubectl("config", "current-context")
    if context != "kind-keeplane":
        raise SystemExit(f"Refusing Kubernetes context {context!r}; expected kind-keeplane")

    results = []
    created = False
    stage = "namespace"
    try:
        kubectl("create", "namespace", NAMESPACE)
        created = True
        stage = "helm install"
        run(HELM, "upgrade", "--install", RELEASE, "deploy/helm/keeplane",
            "--kubeconfig", KUBECONFIG, "--namespace", NAMESPACE,
            "--set", "gateway.mode=existing", "--set", "gateway.install=false",
            "--set", "gateway.url=http://supplied-gateway.supplied-gateway.svc.cluster.local:4000",
            "--set", "gateway.preflightModel=customer-fixture",
            "--set", "app.image=keeplane-preview:kind-local",
            "--set", "app.pullPolicy=Never", "--wait", "--timeout", "120s")
        # Simulate a gateway becoming unavailable after a successful install.
        stage = "gateway outage"
        kubectl("-n", NAMESPACE, "set", "env", "deployment/" + RELEASE + "-app",
                "GATEWAY_URL=http://127.0.0.1:1")
        kubectl("-n", NAMESPACE, "rollout", "status", "deployment/" + RELEASE + "-app",
                "--timeout=120s")
        stage = "service endpoint convergence"
        deadline = time.monotonic() + 30
        endpoint_pod = None
        while time.monotonic() < deadline:
            current = json.loads(kubectl("-n", NAMESPACE, "get", "endpoints",
                                         RELEASE + "-app", "-o", "json"))
            current_addresses = [address for subset in current.get("subsets", [])
                                 for address in subset.get("addresses", [])]
            if len(current_addresses) == 1 and current_addresses[0].get("targetRef", {}).get("name"):
                candidate = current_addresses[0]["targetRef"]["name"]
                pod = json.loads(kubectl("-n", NAMESPACE, "get", "pod", candidate, "-o", "json"))
                configured = next((item.get("value") for item in
                                   pod["spec"]["containers"][0].get("env", [])
                                   if item.get("name") == "GATEWAY_URL"), None)
                if configured == "http://127.0.0.1:1":
                    endpoint_pod = candidate
                    break
            time.sleep(0.5)
        if endpoint_pod is None:
            raise TimeoutError("Service did not switch to the gateway-down app pod")
        stage = "deployment read"
        deployment = json.loads(kubectl("-n", NAMESPACE, "get", "deployment",
                                        RELEASE + "-app", "-o", "json"))
        stage = "service endpoints read"
        endpoints = json.loads(kubectl("-n", NAMESPACE, "get", "endpoints",
                                       RELEASE + "-app", "-o", "json"))
        addresses = [address for subset in endpoints.get("subsets", [])
                     for address in subset.get("addresses", [])]
        ready = deployment["status"].get("readyReplicas")
        results.append(record("K8S-08", ready == 1 and len(addresses) == 1,
                              {"ready_replicas": ready, "service_endpoints": len(addresses)}))

        # Request through the Service DNS, not the pod IP or localhost. This
        # would fail if readiness removed the app from the Service.
        probe = """import json,urllib.request,urllib.error
base='http://keeplane-down-app:3000'
out={}
for path in ('/','/health/app','/health','/api/models'):
 try:
  with urllib.request.urlopen(base+path,timeout=10) as response:
   status=response.status; body=response.read().decode()
 except urllib.error.HTTPError as error:
  status=error.code; body=error.read().decode()
 out[path]={'status':status}
 if path=='/':
  out[path]['warning_present']='id=\"gateway-warning\"' in body
  out[path]['try_again_present']='id=\"try-again\"' in body
print(json.dumps(out))"""
        stage = "service HTTP probe"
        # Endpoint objects can update before the Service dataplane stops
        # sending a few requests to the old, gateway-connected pod.
        deadline = time.monotonic() + 15
        attempts = 0
        observed = None
        last_error = None
        while True:
            try:
                observed = json.loads(kubectl("-n", NAMESPACE, "exec", "pod/" + endpoint_pod,
                                              "--", "python", "-c", probe))
                last_error = None
            except (subprocess.CalledProcessError, ValueError) as error:
                # The pod can be Ready before exec and Service forwarding have
                # both settled after the rollout. The deadline remains bounded.
                observed = None
                last_error = {"type": type(error).__name__,
                              "detail": (error.stderr if isinstance(error, subprocess.CalledProcessError)
                                         else str(error) or "")[:300]}
            attempts += 1
            passed = (observed is not None and
                      observed["/"] == {"status": 200, "warning_present": True,
                                        "try_again_present": True} and
                      observed["/health/app"]["status"] == 200 and
                      observed["/health"]["status"] == 503 and
                      observed["/api/models"]["status"] == 503)
            if passed or time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        results.append(record("K8S-09", passed,
                              {"attempts": attempts, "responses": observed,
                               "last_error": last_error}))
    except (subprocess.CalledProcessError, ValueError, KeyError, TimeoutError) as error:
        results.append(record("K8S gateway-down setup", False,
                              {"stage": stage, "error_type": type(error).__name__}))
    finally:
        if created:
            subprocess.run((HELM, "uninstall", RELEASE, "--kubeconfig", KUBECONFIG,
                            "--namespace", NAMESPACE), cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(("kubectl", "--kubeconfig", KUBECONFIG, "delete", "namespace",
                            NAMESPACE, "--wait=false"), cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(json.dumps({"suite": "Keeplane gateway-down UI availability", "results": results}, indent=2))
    return int(len(results) != 2 or any(item["verdict"] != "pass" for item in results))


if __name__ == "__main__":
    sys.exit(main())
