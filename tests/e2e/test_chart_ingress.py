"""Exercise the Keeplane app-only Ingress on isolated Calico kind."""

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
HOST = "keeplane.example.test"
NAMESPACE = "keeplane-edge-" + uuid.uuid4().hex[:8]


def run(*command, input_text=None, check=True):
    result = subprocess.run(command, cwd=ROOT, input=input_text, text=True,
                            capture_output=True, timeout=300)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-300:]}")
    return result


def kube(*args, input_text=None):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args, input_text=input_text).stdout.strip()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_port(port, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("ingress port-forward exited before accepting connections")
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError("ingress port-forward did not open")


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
    forwarded = None
    with tempfile.TemporaryDirectory(prefix="keeplane-edge-") as directory:
        cert = str(Path(directory) / "cert.pem")
        key = str(Path(directory) / "key.pem")
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", key, "-out", cert, "-days", "1", "-subj", "/CN=" + HOST,
            "-addext", "subjectAltName=DNS:" + HOST,
            "-addext", "basicConstraints=critical,CA:TRUE")
        try:
            kube("create", "namespace", NAMESPACE)
            created = True
            kube("-n", NAMESPACE, "apply", "-f", "tests/e2e/ingress/workloads.yaml")
            kube("-n", NAMESPACE, "wait", "--for=condition=Ready", "pod", "--all", "--timeout=240s")
            kube("-n", NAMESPACE, "create", "secret", "tls", "keeplane-tls",
                 "--cert=" + cert, "--key=" + key)
            ingress = run(HELM, "template", "keeplane", "deploy/helm/keeplane",
                          "-f", "deploy/local/values.yaml", "--set", "app.service.type=ClusterIP",
                          "--set", "ingress.enabled=true", "--set", "ingress.className=nginx",
                          "--set", "ingress.host=" + HOST,
                          "--set", "ingress.tlsSecretName=keeplane-tls",
                          "--show-only", "templates/app-ingress.yaml").stdout
            kube("-n", NAMESPACE, "apply", "-f", "-", input_text=ingress)
            https_port = free_port()
            http_port = free_port()
            forwarded = subprocess.Popen(
                ("kubectl", "--kubeconfig", KUBECONFIG, "-n", "ingress-nginx",
                 "port-forward", "service/ingress-nginx-controller",
                 f"{https_port}:443", f"{http_port}:80"),
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_port(https_port, forwarded)
            https_args = ("curl", "--noproxy", "*", "-sS", "--max-time", "15",
                          "--cacert", cert, "--resolve", f"{HOST}:{https_port}:127.0.0.1")
            deadline = time.monotonic() + 60
            while True:
                root = run(*https_args, f"https://{HOST}:{https_port}/", check=False)
                if root.returncode == 0 and root.stdout == "app:/":
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("TLS route did not become ready: " + root.stderr[-180:])
                time.sleep(1)
            rows.append(case("EDGE-01", root.stdout == "app:/",
                             {"tls_verified": root.returncode == 0, "body": root.stdout}))
            management = run(*https_args,
                             f"https://{HOST}:{https_port}/api/config/resources/llm.model")
            rows.append(case("EDGE-02", management.stdout == "app:/api/config/resources/llm.model",
                             {"body": management.stdout}))
            redirect = run("curl", "--noproxy", "*", "-sS", "--max-time", "15",
                           "--resolve", f"{HOST}:{http_port}:127.0.0.1",
                           "-o", "/dev/null", "-w", "%{http_code}|%{redirect_url}",
                           f"http://{HOST}:{http_port}/")
            status, destination = redirect.stdout.split("|", 1)
            rows.append(case("EDGE-03", status in ("301", "302", "307", "308")
                             and destination.startswith("https://" + HOST),
                             {"http_status": int(status), "redirect_https": destination.startswith("https://" + HOST)}))
            other = run("curl", "--noproxy", "*", "-sS", "-k", "--max-time", "15",
                        "--resolve", f"other.example.test:{https_port}:127.0.0.1",
                        "-o", "/dev/null", "-w", "%{http_code}",
                        f"https://other.example.test:{https_port}/")
            rows.append(case("EDGE-04", other.stdout == "404",
                             {"other_host_status": int(other.stdout)}))
        except Exception as error:
            rows.append(case("EDGE-TRIAL", False,
                             {"error": type(error).__name__, "detail": str(error)[:300]}))
        finally:
            if forwarded:
                forwarded.terminate()
                try:
                    forwarded.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forwarded.kill()
            if created:
                kube("delete", "namespace", NAMESPACE, "--wait=true")
    report = {"suite": "isolated app-only TLS ingress", "context": context,
              "namespace_removed": created, "results": rows, "release_edge_approved": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(len(rows) != 4 or any(row["verdict"] == "fail" for row in rows))


if __name__ == "__main__":
    sys.exit(main())
