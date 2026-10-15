"""Restart only the selected local preview for persistence cases."""

import os
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get(
    "KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig"
)


def restart_app(base):
    if base == "http://127.0.0.1:3000":
        env_file = "/private/tmp/keeplane-accounts-trial/.env"
        subprocess.run(
            ["docker", "compose", "--env-file", env_file, "restart", "app"],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    elif base == "http://127.0.0.1:13000":
        command = ["kubectl", "--kubeconfig", KUBECONFIG]
        context = subprocess.check_output(
            command + ["config", "current-context"], text=True
        ).strip()
        if context != "kind-keeplane":
            raise RuntimeError(f"Refusing to restart Kubernetes context {context!r}")
        previous_pods = subprocess.check_output(
            command
            + ["-n", "keeplane", "get", "pods", "-l", "app=keeplane-app", "-o", "name"],
            text=True,
        ).split()
        subprocess.run(
            command
            + ["-n", "keeplane", "rollout", "restart", "deployment/keeplane-app"],
            check=True,
            capture_output=True,
            text=True,
        )
        # A ready replacement does not mean the old forwarded pod has stopped.
        # Wait for termination before checking the forwarding connection.
        deadline = time.monotonic() + 120
        for pod in previous_pods:
            while subprocess.check_output(
                command
                + ["-n", "keeplane", "get", pod, "--ignore-not-found", "-o", "name"],
                text=True,
            ).strip():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Previous preview pod did not terminate")
                time.sleep(0.5)
        subprocess.run(
            command
            + [
                "-n",
                "keeplane",
                "rollout",
                "status",
                "deployment/keeplane-app",
                "--timeout=120s",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        raise RuntimeError(f"Refusing to restart unknown preview {base!r}")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urlopen(base + "/health/app", timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Preview forwarding did not recover after restart")
