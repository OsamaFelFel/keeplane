"""Open a short-lived loopback path to the isolated existing-gateway app."""

from contextlib import contextmanager
import os
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen


BASE = "http://127.0.0.1:13001"
KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")


@contextmanager
def existing_app():
    context = subprocess.check_output(
        ["kubectl", "--kubeconfig", KUBECONFIG, "config", "current-context"],
        text=True).strip()
    if context != "kind-keeplane":
        raise RuntimeError("Refusing a Kubernetes context other than kind-keeplane")
    process = subprocess.Popen(
        ["kubectl", "--kubeconfig", KUBECONFIG, "-n", "keeplane-existing",
         "port-forward", "service/keeplane-existing-app", "13001:3000",
         "--address", "127.0.0.1"], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                raise RuntimeError("Existing-gateway app port-forward stopped")
            try:
                with urlopen(BASE + "/health/app", timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, OSError, TimeoutError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Existing-gateway app did not become reachable")
            time.sleep(0.1)
        yield BASE
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
