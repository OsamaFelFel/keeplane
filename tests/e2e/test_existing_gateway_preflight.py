"""Check the existing-gateway install gate in the isolated kind trial."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")
HELM = (os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or
        "/private/tmp/keeplane-helm/darwin-amd64/helm")
URL = "http://supplied-gateway.supplied-gateway.svc.cluster.local:4000"
KEY_DIR = Path("/private/tmp/keeplane-accounts-trial")


def run(*args):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=180)


def probe(version, model):
    result = run("kubectl", "--kubeconfig", KUBECONFIG, "-n", "keeplane-existing",
                 "exec", "deploy/keeplane-existing-app", "--", "env",
                 "GATEWAY_URL=" + URL, "EXPECTED_GATEWAY_VERSION=" + version,
                 "GATEWAY_PREFLIGHT_MODEL=" + model,
                 "python", "/app/gateway_preflight.py")
    try:
        output = json.loads(result.stdout)
    except ValueError:
        output = {"error": "preflight did not return JSON"}
    return result.returncode, output


def record(identifier, passed, observed):
    return {"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed}


def main():
    results = []
    context = run("kubectl", "--kubeconfig", KUBECONFIG, "config", "current-context")
    if context.returncode != 0 or context.stdout.strip() != "kind-keeplane":
        raise SystemExit("Refusing a Kubernetes context other than kind-keeplane")
    install = run(HELM, "upgrade", "--install", "keeplane-existing", "deploy/helm/keeplane",
                  "--kubeconfig", KUBECONFIG, "--namespace", "keeplane-existing",
                  "--set", "gateway.mode=existing", "--set", "gateway.install=false",
                  "--set", "gateway.keysSecret=keeplane-gateway-keys",
                  "--set", "gateway.url=" + URL,
                  "--set", "gateway.preflightModel=customer-fixture",
                  "--set", "app.runnerUrls=http://model.supplied-gateway.svc.cluster.local:18080",
                  "--set", "app.image=keeplane-preview:kind-local",
                  "--set", "app.pullPolicy=Never", "--wait", "--timeout", "120s")
    good_code, good = probe("1.6.0", "customer-fixture") if install.returncode == 0 else (1, {})
    results.append(record("K8S-10", install.returncode == 0 and good_code == 0 and
                          good.get("passed") is True and good.get("inference_checked") is True,
                          {"helm_exit": install.returncode, "probe": good}))
    wrong_code, wrong = probe("0.0.0", "customer-fixture") if install.returncode == 0 else (1, {})
    results.append(record("K8S-11", wrong_code != 0 and wrong.get("passed") is False and
                          wrong.get("message") == "Gateway version differs from the pinned integration version",
                          {"exit": wrong_code, "probe": wrong}))
    missing_code, missing = probe("1.6.0", "missing-preflight-model") if install.returncode == 0 else (1, {})
    results.append(record("K8S-12", missing_code != 0 and missing.get("passed") is False and
                          missing.get("message") == "Preflight model is absent from the gateway",
                          {"exit": missing_code, "probe": missing}))
    namespace = "keeplane-preflight-" + str(os.getpid())
    created = run("kubectl", "--kubeconfig", KUBECONFIG, "create", "namespace", namespace)
    if created.returncode == 0:
        try:
            secret = run("kubectl", "--kubeconfig", KUBECONFIG, "-n", namespace,
                         "create", "secret", "generic", "keeplane-gateway-keys",
                         "--from-file=runtime-key=" + str(KEY_DIR / "gateway-runtime-key"),
                         "--from-file=admin-key=" + str(KEY_DIR / "gateway-admin-key"))
            if secret.returncode != 0:
                raise RuntimeError("Could not create disposable gateway key Secret")
            refused = run(HELM, "install", "keeplane-preflight", "deploy/helm/keeplane",
                          "--kubeconfig", KUBECONFIG, "--namespace", namespace,
                          "--set", "gateway.mode=existing", "--set", "gateway.install=false",
                          "--set", "gateway.keysSecret=keeplane-gateway-keys",
                          "--set", "gateway.url=" + URL,
                          "--set", "gateway.expectedVersion=0.0.0",
                          "--set", "gateway.preflightModel=customer-fixture",
                          "--set", "app.image=keeplane-preview:kind-local",
                          "--set", "app.pullPolicy=Never", "--wait", "--timeout", "120s")
            deployed = run("kubectl", "--kubeconfig", KUBECONFIG, "-n", namespace,
                           "get", "deployment", "keeplane-preflight-app")
            results.append(record("K8S-13", refused.returncode != 0 and deployed.returncode != 0,
                                  {"helm_exit": refused.returncode,
                                   "app_deployed": deployed.returncode == 0}))
        finally:
            run(HELM, "uninstall", "keeplane-preflight", "--kubeconfig", KUBECONFIG,
                "--namespace", namespace)
            run("kubectl", "--kubeconfig", KUBECONFIG, "delete", "namespace", namespace,
                "--wait=false")
    else:
        results.append(record("K8S-13", False, {"namespace_created": False}))
    print(json.dumps({"results": results}, indent=2))
    return int(any(result["verdict"] == "fail" for result in results))


if __name__ == "__main__":
    sys.exit(main())
