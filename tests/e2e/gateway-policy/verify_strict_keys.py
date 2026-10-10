"""Isolated strict-key trial against the pinned agentgateway image."""

import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
IMAGE = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]["agentgateway"]
PYTHON_IMAGE = "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"
NAME = "keeplane-policy-pilot-" + uuid.uuid4().hex[:8]
BASE = "http://127.0.0.1:14306"
RUNTIME_KEY = secrets.token_urlsafe(32)
ADMIN_KEY = secrets.token_urlsafe(32)


def command(*args, input_text=None):
    return subprocess.run(args, input=input_text, text=True, capture_output=True,
                          check=True, timeout=90).stdout.strip()


def request(path, key=None, body=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = Request(BASE + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with urlopen(req, timeout=8) as response:
            return response.status
    except HTTPError as error:
        return error.code


def wait_ready():
    for _ in range(60):
        try:
            request("/v1/models")
            return
        except (URLError, TimeoutError, ConnectionResetError):
            time.sleep(0.5)
    raise RuntimeError("Trial gateway did not become ready")


def sibling_probe():
    worker = (ROOT / "tests/e2e/gateway_bypass_worker.py").read_text()
    output = command("docker", "run", "--rm", "-i", "--network", "keeplane-local_default",
                     "-e", "GATEWAY_BASE=http://" + NAME + ":4000",
                     "-e", "MODEL_BASE=http://model:18080",
                     "-e", "MODEL_NAME=local-fixture", PYTHON_IMAGE, "python", "-",
                     input_text=worker)
    return json.loads(output.splitlines()[-1])


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_strict_keys.py OUTPUT_JSON")
    path = Path(sys.argv[1])
    if path.exists():
        raise SystemExit("Evidence output already exists")
    config_path = HERE / "strict-keys.yaml"
    try:
        command("docker", "run", "-d", "--rm", "--name", NAME,
                "--network", "keeplane-local_default", "-p", "127.0.0.1:14306:4000",
                "--tmpfs", "/data:rw", "-e", "TRIAL_RUNTIME_KEY=" + RUNTIME_KEY,
                "-e", "TRIAL_ADMIN_KEY=" + ADMIN_KEY,
                "-v", str(config_path) + ":/config.yaml:ro", IMAGE, "-f", "/config.yaml")
        wait_ready()
        sibling = sibling_probe()
        body = {"model": "local-fixture", "messages": [{"role": "user", "content": "policy trial"}]}
        observations = {
            "sibling_without_credentials": sibling,
            "runtime_key_model_list": request("/v1/models", RUNTIME_KEY),
            "runtime_key_chat": request("/v1/chat/completions", RUNTIME_KEY, body),
            "runtime_key_management": request("/api/config/resources/llm.model", RUNTIME_KEY),
            "admin_key_management": request("/api/config/resources/llm.model", ADMIN_KEY),
            "admin_key_chat": request("/v1/chat/completions", ADMIN_KEY, body),
        }
        trial_passes = (
            all(sibling[field] in (401, 403) for field in
                ("model_list_status", "management_read_status", "direct_chat_status", "forged_chat_status"))
            and sibling["upstream_calls_added"] == 0
            and observations["runtime_key_model_list"] == 200
            and observations["runtime_key_chat"] == 200
            and observations["runtime_key_management"] in (401, 403)
            and observations["admin_key_management"] == 200
            and observations["admin_key_chat"] in (401, 403))
        report = {"trial": "isolated strict runtime and UI keys", "image": IMAGE,
                  "observations": observations, "trial_passes": trial_passes,
                  "release_policy_passes": False}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        if not trial_passes:
            raise RuntimeError("Strict-key trial failed; inspect versioned evidence")
    finally:
        subprocess.run(["docker", "rm", "-f", NAME], capture_output=True, text=True, timeout=30)


if __name__ == "__main__":
    main()
