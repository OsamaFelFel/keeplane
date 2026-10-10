"""Run the actual Keeplane chart behind TLS Ingress and Calico on isolated kind."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get("KEEPLANE_NETPOL_KUBECONFIG", "/private/tmp/keeplane-netpol-kubeconfig")
HELM = os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or "/private/tmp/keeplane-helm/darwin-amd64/helm"
PASSWORD = Path("/private/tmp/keeplane-accounts-trial/first-admin-password")
KEYS = Path("/private/tmp/keeplane-accounts-trial")
HOST = "keeplane.example.test"
NAMESPACE = "keeplane-full-" + uuid.uuid4().hex[:8]


def run(*command, check=True):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=360)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-350:]}")
    return result


def kube(*args):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args).stdout.strip()


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def record(rows, identifier, passed, observed):
    rows.append({"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed})


def ready_gateway_pods():
    pods = json.loads(kube("-n", NAMESPACE, "get", "pods", "-l",
                          "app.kubernetes.io/name=agentgateway-standalone,app.kubernetes.io/instance=keeplane",
                          "-o", "json"))["items"]
    return [pod["metadata"]["name"] for pod in pods
            if pod["status"].get("phase") == "Running" and
            any(condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in pod["status"].get("conditions", []))]


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
    https_port = port()
    http_port = port()
    with tempfile.TemporaryDirectory(prefix="keeplane-full-edge-") as directory:
        temporary = Path(directory)
        cert = temporary / "cert.pem"
        key = temporary / "key.pem"
        cookie = temporary / "cookie.txt"
        login = temporary / "login.json"
        ask = temporary / "ask.json"
        setup = temporary / "setup.json"
        login.write_text(json.dumps({"username": "first-admin", "password": PASSWORD.read_text().strip()}))
        login.chmod(0o600)
        ask.write_text(json.dumps({"model": "local-fixture", "prompt": "fixture"}))
        setup.write_text(json.dumps({"key_choice": "none", "approved_classes": ["Public"]}))
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=" + HOST, "-addext", "subjectAltName=DNS:" + HOST,
            "-addext", "basicConstraints=critical,CA:TRUE")
        try:
            kube("create", "namespace", NAMESPACE)
            created = True
            kube("-n", NAMESPACE, "create", "secret", "generic", "keeplane-first-admin",
                 "--from-file=first-admin-password=" + str(PASSWORD))
            kube("-n", NAMESPACE, "create", "secret", "generic", "keeplane-gateway-keys",
                 *["--from-file=" + name + "=" + str(KEYS / ("gateway-" + name))
                   for name in ("runtime-key", "admin-key", "runtime-key-hash", "admin-key-hash")])
            kube("-n", NAMESPACE, "create", "secret", "tls", "keeplane-tls",
                 "--cert=" + str(cert), "--key=" + str(key))
            kube("-n", NAMESPACE, "create", "configmap", "model-fixture",
                 "--from-file=mock_model.py=tests/fixtures/mock_model.py")
            kube("-n", NAMESPACE, "apply", "-f", "deploy/local/model-fixture.yaml")
            kube("-n", NAMESPACE, "apply", "-f", "deploy/local/postgres-fixture.yaml")
            kube("-n", NAMESPACE, "rollout", "status", "deployment/model", "--timeout=240s")
            kube("-n", NAMESPACE, "rollout", "status", "deployment/postgres", "--timeout=240s")
            run(HELM, "--kubeconfig", KUBECONFIG, "install", "keeplane",
                "deploy/helm/keeplane", "--namespace", NAMESPACE,
                "-f", "deploy/local/values.yaml",
                "--set", "app.service.type=ClusterIP",
                "--set", "app.runnerUrls=http://model:18080",
                "--set", "app.localTrial.publicOriginAliases=https://" + HOST + f":{https_port}",
                "--set", "networkPolicy.gatewayIngressEnabled=true",
                "--set", "ingress.enabled=true", "--set", "ingress.className=nginx",
                "--set", "ingress.host=" + HOST,
                "--set", "ingress.tlsSecretName=keeplane-tls",
                "--set", "agentgateway-standalone.replicaCount=2",
                "--wait", "--timeout", "300s")
            kube("-n", NAMESPACE, "rollout", "status", "deployment/keeplane-app", "--timeout=240s")
            kube("-n", NAMESPACE, "rollout", "status", "deployment/keeplane", "--timeout=240s")
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
                    raise RuntimeError("Full-product TLS route did not become ready: " + root.stderr[-150:])
                time.sleep(1)
            record(rows, "FULL-01", True, {"tls_verified": True, "anonymous_root_status": 302})
            signed = run(*base, "-c", str(cookie), "-b", str(cookie), "-o", "/dev/null",
                         "-w", "%{http_code}", "-X", "POST",
                         "-H", "Content-Type: application/json", "-H", "X-Keeplane-Action: 1",
                         "-H", "Origin: " + url,
                         "--data-binary", "@" + str(login), url + "/api/session")
            identity = run(*base, "-b", str(cookie), "-o", "/dev/null", "-w", "%{http_code}",
                           url + "/api/identity")
            record(rows, "FULL-02", signed.stdout == "200" and identity.stdout == "200",
                   {"session_status": signed.stdout, "identity_status": identity.stdout})
            deadline = time.monotonic() + 25
            while True:
                models = run(*base, "-b", str(cookie), "-o", "/dev/null", "-w", "%{http_code}",
                             url + "/api/models", check=False)
                if models.returncode == 0 and models.stdout == "200":
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(1)
            record(rows, "FULL-03", models.returncode == 0 and models.stdout == "200",
                   {"models_status": models.stdout, "curl_exit": models.returncode})
            sibling = kube("-n", NAMESPACE, "exec", "deployment/model", "--", "python", "-c",
                           "import urllib.request;\ntry: urllib.request.urlopen('http://keeplane:4000/v1/models', timeout=3); print('allowed')\nexcept Exception as error: print(type(error).__name__ + ':' + type(getattr(error, 'reason', None)).__name__)")
            record(rows, "FULL-04", sibling == "URLError:TimeoutError",
                   {"sibling_result": sibling})
            policy = json.loads(kube("-n", NAMESPACE, "get", "networkpolicy",
                                     "keeplane-gateway-ingress", "-o", "json"))
            record(rows, "FULL-05", policy["spec"]["podSelector"]["matchLabels"].get(
                "app.kubernetes.io/instance") == "keeplane",
                   {"gateway_policy_present": True})
            initial_pods = ready_gateway_pods()
            record(rows, "FULL-06", len(initial_pods) == 2,
                   {"ready_gateway_replicas": len(initial_pods)})
            model_response = run(*base, "-b", str(cookie), url + "/api/models")
            model = next((item for item in json.loads(model_response.stdout).get("models", [])
                          if item.get("id") == "local-fixture"), {})
            setup_status = None
            if model and not model.get("approved"):
                setup_response = run(*base, "-b", str(cookie), "-o", "/dev/null", "-w", "%{http_code}",
                                     "-X", "POST", "-H", "Content-Type: application/json",
                                     "-H", "X-Keeplane-Action: 1", "-H", "Origin: " + url,
                                     "--data-binary", "@" + str(setup),
                                     url + "/api/models/local-fixture/setup", check=False)
                setup_status = setup_response.stdout

            def ask_fixture():
                response = run(*base, "-b", str(cookie), "-X", "POST",
                               "-H", "Content-Type: application/json", "-H", "X-Keeplane-Action: 1",
                               "-H", "Origin: " + url, "--data-binary", "@" + str(ask),
                               "-o", str(temporary / "answer.json"), "-w", "%{http_code}",
                               url + "/api/ask", check=False)
                try:
                    answer = json.loads((temporary / "answer.json").read_text())
                except (ValueError, FileNotFoundError):
                    answer = {}
                return response.stdout, answer.get("answer")

            before_status, before_answer = ask_fixture()
            record(rows, "FULL-07", bool(model) and setup_status in (None, "200") and
                   before_status == "200" and before_answer == "mock answer",
                   {"model_found": bool(model), "setup_status": setup_status,
                    "ask_status": before_status, "expected_answer": before_answer == "mock answer"})
            if len(initial_pods) == 2:
                kube("-n", NAMESPACE, "delete", "pod", initial_pods[0],
                     "--grace-period=0", "--force", "--wait=true")
                remaining = ready_gateway_pods()
                after_status, after_answer = ask_fixture()
                record(rows, "FULL-08", remaining == [initial_pods[1]] and after_status == "200" and
                       after_answer == "mock answer",
                       {"only_original_survivor_ready": remaining == [initial_pods[1]],
                        "ready_gateway_replicas": len(remaining), "ask_status": after_status,
                        "expected_answer": after_answer == "mock answer"})
            else:
                record(rows, "FULL-08", False, {"reason": "two gateway replicas were not ready"})
        except Exception as error:
            record(rows, "FULL-TRIAL", False,
                   {"error": type(error).__name__, "detail": str(error)[:350]})
        finally:
            if forwarded:
                forwarded.terminate()
                try:
                    forwarded.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forwarded.kill()
            if created:
                kube("delete", "namespace", NAMESPACE, "--wait=true")
    report = {"suite": "full Keeplane chart on enforcing Calico with TLS Ingress",
              "context": context, "namespace_removed": created, "results": rows,
              "production_release_approved": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(len(rows) != 8 or any(row["verdict"] == "fail" for row in rows))


if __name__ == "__main__":
    sys.exit(main())
