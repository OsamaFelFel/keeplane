"""Compare the local trial lock with Docker, kind and Helm as actually running."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen
from protected_preview import login_if_protected


ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())
KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")
HELM = os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or "/private/tmp/keeplane-helm/darwin-amd64/helm"


def output(*command):
    return subprocess.check_output(command, cwd=ROOT, text=True, timeout=30).strip()


def kubectl(*args):
    return output("kubectl", "--kubeconfig", KUBECONFIG, *args)


def image(namespace, deployment):
    data = json.loads(kubectl("-n", namespace, "get", "deployment", deployment, "-o", "json"))
    return data["spec"]["template"]["spec"]["containers"][0]["image"]


def status(url):
    login_if_protected(url)
    with urlopen(url + "/api/status", timeout=10) as response:
        return json.load(response)["gateway"]["version"]


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    context = kubectl("config", "current-context")
    if context != "kind-keeplane":
        raise SystemExit(f"Refusing Kubernetes context {context!r}; expected kind-keeplane")

    images = LOCK["images"]
    model = LOCK["model"]
    digest = file_sha256(ROOT / model["path"])
    node = output("docker", "inspect", "--format", "{{.Config.Image}}", "keeplane-control-plane")
    observed_docker = {
        service: output("docker", "inspect", "--format", "{{.Config.Image}}", f"keeplane-local-{service}-1")
        for service in ("gateway", "qwen", "app")
    }
    observed_kind = {
        "managed_gateway": image("keeplane", "keeplane"),
        "supplied_gateway": image("supplied-gateway", "supplied-gateway"),
        "qwen": image("keeplane", "qwen"),
        "postgres": image("keeplane", "postgres"),
    }
    releases = {(item["namespace"], item["name"]): item["chart"] for item in
                json.loads(output(HELM, "list", "--kubeconfig", KUBECONFIG, "-A", "-o", "json"))}
    versions = {"docker": status("http://127.0.0.1:3000"),
                "kind": status("http://127.0.0.1:13000")}

    checks = [
        ("LOCK-01", digest == model["sha256"] and node == images["kind_node"],
         {"model_sha256": digest, "kind_node_image": node}),
        ("LOCK-02", observed_docker == {"gateway": images["agentgateway"],
                                        "qwen": images["llama_cpp"],
                                        "app": images["python_fixture"]}, observed_docker),
        ("LOCK-03", observed_kind == {"managed_gateway": images["agentgateway"],
                                      "supplied_gateway": images["agentgateway"],
                                      "qwen": images["llama_cpp"],
                                      "postgres": images["postgres"]}
         and releases.get(("keeplane", "keeplane")) == LOCK["charts"]["keeplane"]
         and releases.get(("keeplane-existing", "keeplane-existing")) == LOCK["charts"]["keeplane"]
         and releases.get(("supplied-gateway", "supplied-gateway")) == LOCK["charts"]["agentgateway"],
         {"images": observed_kind, "charts": {f"{n}/{r}": releases.get((n, r)) for n, r in
          (("keeplane", "keeplane"), ("keeplane-existing", "keeplane-existing"),
           ("supplied-gateway", "supplied-gateway"))}}),
        ("LOCK-04", all(version == LOCK["runtime"]["agentgateway"] for version in versions.values()),
         versions),
    ]
    print(json.dumps({"suite": "Keeplane local stack lock", "lock": "deploy/local/stack.lock.json",
                      "results": [{"case": case, "verdict": "pass" if okay else "fail",
                                   "observed": observed} for case, okay, observed in checks]}, indent=2))
    return 0 if all(okay for _, okay, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
