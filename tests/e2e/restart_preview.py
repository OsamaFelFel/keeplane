"""Restart only the selected local preview for persistence cases."""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")


def restart_app(base):
    if base == "http://127.0.0.1:3000":
        env_file = "/private/tmp/keeplane-accounts-trial/.env"
        subprocess.run(["docker", "compose", "--env-file", env_file, "restart", "app"],
                       check=True, cwd=ROOT, capture_output=True, text=True)
    elif base == "http://127.0.0.1:13000":
        command = ["kubectl", "--kubeconfig", KUBECONFIG]
        context = subprocess.check_output(command + ["config", "current-context"], text=True).strip()
        if context != "kind-keeplane":
            raise RuntimeError(f"Refusing to restart Kubernetes context {context!r}")
        subprocess.run(command + ["-n", "keeplane", "rollout", "restart",
                                  "deployment/keeplane-app"], check=True,
                       capture_output=True, text=True)
        subprocess.run(command + ["-n", "keeplane", "rollout", "status",
                                  "deployment/keeplane-app", "--timeout=120s"], check=True,
                       capture_output=True, text=True)
    else:
        raise RuntimeError(f"Refusing to restart unknown preview {base!r}")
