"""Capture direct-access gaps without claiming the release policy passed."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
WORKER = (Path(__file__).with_name("gateway_bypass_worker.py")).read_text()
KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")
PYTHON_IMAGE = "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"


def run(*command, input_text=None):
    return subprocess.run(command, cwd=ROOT, text=True, input=input_text,
                          capture_output=True, check=True, timeout=120).stdout.strip()


def kube(namespace, *args, input_text=None):
    return run("kubectl", "--kubeconfig", KUBECONFIG, "-n", namespace, *args,
               input_text=input_text)


def worker_result(stdout):
    return json.loads(stdout.splitlines()[-1])


def docker_trial():
    return worker_result(run("docker", "run", "--rm", "-i", "--network", "keeplane-local_default",
                             "-e", "GATEWAY_BASE=http://gateway:4000",
                             "-e", "MODEL_BASE=http://model:18080",
                             "-e", "MODEL_NAME=local-fixture", PYTHON_IMAGE,
                             "python", "-", input_text=WORKER))


def kind_trial(namespace, gateway, model):
    pod = "gateway-bypass-probe-" + uuid.uuid4().hex[:8]
    created = False
    try:
        kube(namespace, "run", pod, "--image=" + PYTHON_IMAGE,
             "--image-pull-policy=IfNotPresent", "--restart=Never",
             "--overrides={\"spec\":{\"automountServiceAccountToken\":false}}",
             "--env=GATEWAY_BASE=http://" + gateway + ":4000",
             "--env=MODEL_BASE=http://model:18080",
             "--env=MODEL_NAME=" + model,
             "--command", "--", "sleep", "600")
        created = True
        kube(namespace, "wait", "--for=condition=Ready", "pod/" + pod, "--timeout=120s")
        return worker_result(kube(namespace, "exec", "-i", "pod/" + pod,
                                  "--", "python", "-", input_text=WORKER))
    finally:
        if created:
            kube(namespace, "delete", "pod/" + pod, "--ignore-not-found=true", "--wait=true")


def public_status(base, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(base + path, data=data,
                  headers={"Content-Type": "application/json", "X-Keeplane-User": "first-admin",
                           "X-Keeplane-Project": "other-project"})
    try:
        with urlopen(req, timeout=15) as response:
            return response.status
    except HTTPError as error:
        return error.code


def public_trial(base):
    return {"models": public_status(base, "/api/models"),
            "management": public_status(base, "/api/config/resources/llm.model"),
            "chat": public_status(base, "/api/ask", {"model": "local-fixture", "prompt": "probe"})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--targets", choices=("all", "docker"), default="all")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence output already exists")
    context = "not checked"
    if args.targets == "all":
        context = run("kubectl", "--kubeconfig", KUBECONFIG, "config", "current-context")
        if context != "kind-keeplane":
            raise RuntimeError(f"Refusing Kubernetes context {context!r}")
    observations = {
        "docker_managed": docker_trial(),
        "public_docker": public_trial("http://127.0.0.1:3000"),
    }
    if args.targets == "all":
        observations["kind_managed"] = kind_trial("keeplane", "keeplane", "local-fixture")
        observations["kind_supplied"] = kind_trial("supplied-gateway", "supplied-gateway", "customer-fixture")
        observations["public_kind"] = public_trial("http://127.0.0.1:13000")
    for name in ("docker_managed", "kind_managed", "kind_supplied"):
        if name not in observations:
            continue
        row = observations[name]
        row["tested_probe_passes"] = (
            row["model_list_status"] in (401, 403) and
            row["management_read_status"] in (401, 403, 404) and
            row["direct_chat_status"] in (401, 403) and
            row["forged_chat_status"] in (401, 403) and
            row["upstream_calls_added"] == 0)
    for name in ("public_docker", "public_kind"):
        if name not in observations:
            continue
        observations[name]["tested_probe_passes"] = all(
            value in (401, 403, 404) for key, value in observations[name].items()
            if key != "tested_probe_passes")
    report = {"suite": "current gateway bypass diagnostic", "time_utc": datetime.now(timezone.utc).isoformat(),
              "gateway_image": json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]["agentgateway"],
              "context": context, "observations": observations, "release_gateway_selected": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
