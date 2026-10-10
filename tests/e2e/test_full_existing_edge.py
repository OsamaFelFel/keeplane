"""Run the protected app against an independently installed gateway on Calico."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from test_full_product_edge import HELM, HOST, KEYS, KUBECONFIG, PASSWORD, ROOT, port


APP_NS = "keeplane-existing-edge-" + uuid.uuid4().hex[:8]
GATEWAY_NS = APP_NS + "-gateway"
GATEWAY_URL = f"http://customer-gateway.{GATEWAY_NS}.svc.cluster.local:4000"


def run(*command, input_text=None, check=True):
    result = subprocess.run(command, cwd=ROOT, text=True, input=input_text,
                            capture_output=True, timeout=360)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-350:]}")
    return result


def kube(*args, input_text=None):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args, input_text=input_text).stdout.strip()


def record(rows, identifier, passed, observed):
    rows.append({"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed})


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
    created = []
    forwarded = None
    https_port = port()
    http_port = port()
    with tempfile.TemporaryDirectory(prefix="keeplane-existing-edge-") as directory:
        temporary = Path(directory)
        cert = temporary / "cert.pem"
        key = temporary / "key.pem"
        cookie = temporary / "cookie.txt"
        login = temporary / "login.json"
        registration = temporary / "registration.json"
        ask = temporary / "ask.json"
        login.write_text(json.dumps({"username": "first-admin", "password": PASSWORD.read_text().strip()}))
        login.chmod(0o600)
        registration.write_text(json.dumps({"name": "customer-managed", "model": "mock-local",
                                            "source": "runner", "address": "http://model." +
                                            GATEWAY_NS + ".svc.cluster.local:18080",
                                            "approved_classes": ["Public"]}))
        ask.write_text(json.dumps({"model": "customer-managed", "prompt": "fixture"}))
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=" + HOST, "-addext", "subjectAltName=DNS:" + HOST,
            "-addext", "basicConstraints=critical,CA:TRUE")
        try:
            for namespace in (GATEWAY_NS, APP_NS):
                kube("create", "namespace", namespace)
                created.append(namespace)
                kube("-n", namespace, "create", "secret", "generic", "keeplane-gateway-keys",
                     *["--from-file=" + name + "=" + str(KEYS / ("gateway-" + name))
                       for name in ("runtime-key", "admin-key", "runtime-key-hash", "admin-key-hash")])
            kube("-n", GATEWAY_NS, "create", "configmap", "model-fixture",
                 "--from-file=mock_model.py=tests/fixtures/mock_model.py")
            kube("-n", GATEWAY_NS, "apply", "-f", "deploy/local/model-fixture.yaml")
            kube("-n", GATEWAY_NS, "apply", "-f", "deploy/local/postgres-fixture.yaml")
            kube("-n", GATEWAY_NS, "rollout", "status", "deployment/model", "--timeout=240s")
            kube("-n", GATEWAY_NS, "rollout", "status", "deployment/postgres", "--timeout=240s")
            run(HELM, "--kubeconfig", KUBECONFIG, "install", "customer-gateway",
                "deploy/helm/keeplane/charts/agentgateway-standalone-v1.6.0.tgz",
                "--namespace", GATEWAY_NS, "-f", "deploy/local/supplied-gateway-values.yaml",
                "--wait", "--timeout", "300s")
            kube("-n", APP_NS, "create", "secret", "generic", "keeplane-first-admin",
                 "--from-file=first-admin-password=" + str(PASSWORD))
            kube("-n", APP_NS, "create", "secret", "tls", "keeplane-tls",
                 "--cert=" + str(cert), "--key=" + str(key))
            policy = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                      "metadata": {"name": "customer-gateway-ingress"},
                      "spec": {"podSelector": {"matchLabels": {
                          "app.kubernetes.io/name": "agentgateway-standalone",
                          "app.kubernetes.io/instance": "customer-gateway"}},
                          "policyTypes": ["Ingress"], "ingress": [{"from": [
                              {"namespaceSelector": {"matchLabels": {
                                  "kubernetes.io/metadata.name": APP_NS}},
                               "podSelector": {"matchLabels": {"app": "keeplane-app"}}},
                              {"namespaceSelector": {"matchLabels": {
                                  "kubernetes.io/metadata.name": APP_NS}},
                               "podSelector": {"matchLabels": {"app": "keeplane-gateway-preflight"}}}],
                              "ports": [{"protocol": "TCP", "port": 4000}]}]}}
            kube("-n", GATEWAY_NS, "apply", "-f", "-", input_text=json.dumps(policy))
            run(HELM, "--kubeconfig", KUBECONFIG, "install", "keeplane",
                "deploy/helm/keeplane", "--namespace", APP_NS,
                "-f", "deploy/local/existing-values.yaml",
                "--set", "app.service.type=ClusterIP",
                "--set", "app.runnerUrls=http://model." + GATEWAY_NS + ".svc.cluster.local:18080",
                "--set", "app.localTrial.publicOriginAliases=https://" + HOST + f":{https_port}",
                "--set", "gateway.url=" + GATEWAY_URL,
                "--set", "ingress.enabled=true", "--set", "ingress.className=nginx",
                "--set", "ingress.host=" + HOST, "--set", "ingress.tlsSecretName=keeplane-tls",
                "--wait", "--timeout", "300s")
            app_deployments = json.loads(kube("-n", APP_NS, "get", "deployment", "-o", "json"))["items"]
            record(rows, "EXEDGE-01", [item["metadata"]["name"] for item in app_deployments] ==
                   ["keeplane-app"], {"app_deployments": [item["metadata"]["name"]
                                                 for item in app_deployments],
                                      "gateway_preflight_passed": True})
            forwarded = subprocess.Popen(
                ("kubectl", "--kubeconfig", KUBECONFIG, "-n", "ingress-nginx",
                 "port-forward", "service/ingress-nginx-controller",
                 f"{https_port}:443", f"{http_port}:80"), cwd=ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = ("curl", "--noproxy", "*", "-sS", "--max-time", "15",
                    "--cacert", str(cert), "--resolve", f"{HOST}:{https_port}:127.0.0.1")
            url = f"https://{HOST}:{https_port}"
            deadline = time.monotonic() + 60
            while True:
                root = run(*base, "-o", "/dev/null", "-w", "%{http_code}", url + "/", check=False)
                if root.returncode == 0 and root.stdout == "302":
                    break
                if forwarded.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Customer-run TLS route did not become ready")
                time.sleep(1)
            signed = run(*base, "-c", str(cookie), "-b", str(cookie), "-o", "/dev/null",
                         "-w", "%{http_code}", "-X", "POST", "-H", "Content-Type: application/json",
                         "-H", "X-Keeplane-Action: 1", "-H", "Origin: " + url,
                         "--data-binary", "@" + str(login), url + "/api/session")
            identity = run(*base, "-b", str(cookie), "-o", "/dev/null", "-w", "%{http_code}",
                           url + "/api/identity")
            record(rows, "EXEDGE-02", root.stdout == "302" and signed.stdout == "200" and
                   identity.stdout == "200", {"tls_verified": True, "anonymous_status": root.stdout,
                                                "session_status": signed.stdout,
                                                "identity_status": identity.stdout})
            app_probe = kube("-n", APP_NS, "exec", "deployment/keeplane-app", "--", "python", "-c",
                             "import urllib.request,urllib.error\ntry: urllib.request.urlopen('" +
                             GATEWAY_URL + "/v1/models', timeout=3); print('allowed')\nexcept urllib.error.HTTPError as error: print('HTTP:' + str(error.code))\nexcept Exception as error: print(type(error).__name__ + ':' + type(getattr(error, 'reason', None)).__name__)")
            registration_file = temporary / "registration-result.json"
            registration_result = run(*base, "-b", str(cookie), "-o", str(registration_file),
                                      "-w", "%{http_code}", "-X", "POST",
                                      "-H", "Content-Type: application/json",
                                      "-H", "X-Keeplane-Action: 1", "-H", "Origin: " + url,
                                      "--data-binary", "@" + str(registration),
                                      url + "/api/models", check=False)
            try:
                registration_error = json.loads(registration_file.read_text()).get("error")
            except (ValueError, FileNotFoundError):
                registration_error = None
            answer_file = temporary / "answer.json"
            answer_result = run(*base, "-b", str(cookie), "-o", str(answer_file),
                                "-w", "%{http_code}", "-X", "POST",
                                "-H", "Content-Type: application/json", "-H", "X-Keeplane-Action: 1",
                                "-H", "Origin: " + url, "--data-binary", "@" + str(ask),
                                url + "/api/ask", check=False)
            try:
                answer = json.loads(answer_file.read_text()).get("answer")
            except (ValueError, FileNotFoundError):
                answer = None
            record(rows, "EXEDGE-03", registration_result.stdout == "200" and
                   answer_result.stdout == "200" and answer == "mock answer",
                   {"app_gateway_probe": app_probe, "registration_status": registration_result.stdout,
                    "registration_error": registration_error, "ask_status": answer_result.stdout,
                    "expected_answer": answer == "mock answer"})
            sibling = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "sibling"},
                       "spec": {"automountServiceAccountToken": False, "containers": [{
                           "name": "caller", "image": "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a",
                           "imagePullPolicy": "IfNotPresent", "command": ["python", "-c",
                               "import time; time.sleep(600)"]}]}}
            kube("-n", APP_NS, "apply", "-f", "-", input_text=json.dumps(sibling))
            kube("-n", APP_NS, "wait", "--for=condition=Ready", "pod/sibling", "--timeout=240s")
            probe = "import urllib.request\ntry: urllib.request.urlopen('" + GATEWAY_URL + "/v1/models', timeout=3); print('allowed')\nexcept Exception as error: print(type(error).__name__ + ':' + type(getattr(error, 'reason', None)).__name__)"
            blocked = kube("-n", APP_NS, "exec", "pod/sibling", "--", "python", "-c", probe)
            record(rows, "EXEDGE-04", blocked == "URLError:TimeoutError",
                   {"sibling_result": blocked})
            outside = run(*base, "-o", "/dev/null", "-w", "%{http_code}",
                          url + "/v1/models", check=False)
            record(rows, "EXEDGE-05", outside.stdout == "302",
                   {"public_gateway_route_status": outside.stdout})
        except Exception as error:
            record(rows, "EXEDGE-TRIAL", False,
                   {"error": type(error).__name__, "detail": str(error)[:350]})
        finally:
            if forwarded:
                forwarded.terminate()
                try:
                    forwarded.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forwarded.kill()
            for namespace in reversed(created):
                kube("delete", "namespace", namespace, "--wait=true")
    report = {"suite": "customer-run gateway behind TLS and enforcing Calico",
              "context": context, "namespaces_removed": len(created) == 2,
              "results": rows, "production_release_approved": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(len(rows) != 5 or any(row["verdict"] == "fail" for row in rows))


if __name__ == "__main__":
    sys.exit(main())
