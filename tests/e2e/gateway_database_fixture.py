"""Create disposable database credentials without command-line secrets."""

import base64
import json
import secrets
import subprocess


def database_secret(kubeconfig, namespace, password=None):
    password = password or secrets.token_urlsafe(32)
    manifest = {"apiVersion": "v1", "kind": "Secret",
                "metadata": {"name": "keeplane-gateway-db", "namespace": namespace},
                "type": "Opaque", "data": {
                    "password": base64.b64encode(password.encode()).decode()}}
    result = subprocess.run(
        ("kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"),
        input=json.dumps(manifest), text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Disposable database Secret could not be applied")
    return password
