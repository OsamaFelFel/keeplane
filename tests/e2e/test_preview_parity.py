"""Check that Docker and kind serve the same protected build and API surfaces."""

import json
from pathlib import Path
import subprocess
import sys

from test_accounts import Browser, RUNTIME


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = "/private/tmp/keeplane-kind-kubeconfig"
FINGERPRINT = """
import hashlib, json
from pathlib import Path
paths = [Path('/app/server.py'), Path('/app/django_api/views.py')]
paths += sorted(Path('/ui/web/dist').rglob('*'))
print(json.dumps({str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in paths if path.is_file()}))
"""


def inside(kind):
    if kind:
        prefix = ["kubectl", "--kubeconfig", KUBECONFIG]
        context = subprocess.check_output(prefix + ["config", "current-context"], text=True).strip()
        if context != "kind-keeplane":
            raise RuntimeError("Refusing a Kubernetes context other than kind-keeplane")
        command = prefix + ["-n", "keeplane", "exec", "deployment/keeplane-app", "--"]
    else:
        command = ["docker", "compose", "--env-file",
                   "/private/tmp/keeplane-accounts-trial/.env", "exec", "-T", "app"]
    result = subprocess.run(command + ["python", "-c", FINGERPRINT], cwd=ROOT,
                            text=True, capture_output=True, check=True, timeout=30)
    return json.loads(result.stdout)


def surface(base):
    browser = Browser(base)
    login_status, _, _, _, _ = browser.login(
        "first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    routes = {}
    for name, path in (("users", "/users"), ("data_classes", "/data-classes"),
                       ("audit", "/audit"), ("models", "/app/models")):
        status, _, page = browser.page(path)
        routes[name] = status == 200 and 'id="root"' in page
    apis = {}
    for name, path, key in (("identity", "/api/identity", "role"),
                            ("users", "/api/users", "users"),
                            ("data_classes", "/api/data-classes", "classes"),
                            ("audit", "/api/audit/options", "options"),
                            ("models", "/api/models", "models"),
                            ("gateway", "/api/status", "gateway")):
        status, body, _ = browser.fetch(path)
        apis[name] = status == 200 and isinstance(body, dict) and key in body
    return {"login": login_status == 200, "routes": routes, "apis": apis}


def main():
    rows = []
    docker = inside(False)
    kind = inside(True)
    rows.append({"case": "PARITY-01", "verdict": "pass" if docker == kind and docker else "fail",
                 "observed": {"matching_files": len(docker), "identical": docker == kind,
                              "docker_only": sorted(set(docker) - set(kind)),
                              "kind_only": sorted(set(kind) - set(docker)),
                              "different": sorted(path for path in docker.keys() & kind.keys()
                                                  if docker[path] != kind[path])}})
    observed = {"docker": surface("http://127.0.0.1:3000"),
                "kind": surface("http://127.0.0.1:13000")}
    passed = all(item["login"] and all(item["routes"].values()) and all(item["apis"].values())
                 for item in observed.values())
    rows.append({"case": "PARITY-02", "verdict": "pass" if passed else "fail",
                 "observed": observed})
    print(json.dumps({"suite": "Docker and kind protected-preview parity", "results": rows}, indent=2))
    return int(not all(row["verdict"] == "pass" for row in rows))


if __name__ == "__main__":
    sys.exit(main())
