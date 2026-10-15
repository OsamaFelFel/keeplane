"""Run the actual Keeplane chart behind TLS Ingress and Calico on isolated kind."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import uuid
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get(
    "KEEPLANE_NETPOL_KUBECONFIG", "/private/tmp/keeplane-netpol-kubeconfig"
)
HELM = (
    os.environ.get("KEEPLANE_HELM_BIN")
    or shutil.which("helm")
    or "/private/tmp/keeplane-helm/darwin-amd64/helm"
)
PASSWORD = Path("/private/tmp/keeplane-accounts-trial/first-admin-password")
KEYS = Path("/private/tmp/keeplane-accounts-trial")
HOST = "keeplane.example.test"
NAMESPACE = "keeplane-full-" + uuid.uuid4().hex[:8]


def run(*command, check=True):
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, timeout=360
    )
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-350:]}")
    return result


def kube(*args):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args).stdout.strip()


def prepare_app_image():
    """Use the current local app build in the disposable Calico cluster."""
    if kube("config", "current-context") != "kind-keeplane-netpol":
        raise RuntimeError("Refusing to load images outside kind-keeplane-netpol")
    run(
        "kind",
        "load",
        "docker-image",
        "keeplane-preview:kind-local",
        "--name",
        "keeplane-netpol",
    )


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def record(rows, identifier, passed, observed):
    rows.append(
        {
            "case": identifier,
            "verdict": "pass" if passed else "fail",
            "observed": observed,
        }
    )


def ready_gateway_pods():
    pods = json.loads(
        kube(
            "-n",
            NAMESPACE,
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/name=agentgateway-standalone,app.kubernetes.io/instance=keeplane",
            "-o",
            "json",
        )
    )["items"]
    return [
        pod["metadata"]["name"]
        for pod in pods
        if pod["status"].get("phase") == "Running"
        and any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in pod["status"].get("conditions", [])
        )
    ]


def gateway_snapshot(pod):
    """Read one replica directly; record model IDs only, never gateway keys."""
    local_port = port()
    forwarded = subprocess.Popen(
        (
            "kubectl",
            "--kubeconfig",
            KUBECONFIG,
            "-n",
            NAMESPACE,
            "port-forward",
            "pod/" + pod,
            f"{local_port}:4000",
            "--address=127.0.0.1",
        ),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:

        def read(path, key_name):
            token = (KEYS / ("gateway-" + key_name)).read_text().strip()
            request = Request(
                f"http://127.0.0.1:{local_port}" + path,
                headers={"Authorization": "Bearer " + token},
            )
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        deadline = time.monotonic() + 15
        while True:
            try:
                models = read("/v1/models", "runtime-key")
                resources = read("/api/config/resources/llm.model", "admin-key")
                return {
                    "runtime": sorted(item["id"] for item in models.get("data", [])),
                    "management": sorted(
                        item["id"] for item in resources.get("resources", [])
                    ),
                }
            except (OSError, URLError, ValueError):
                if forwarded.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Could not read one gateway replica")
                time.sleep(0.2)
    finally:
        forwarded.terminate()
        try:
            forwarded.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forwarded.kill()
