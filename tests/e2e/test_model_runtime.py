"""Check the pinned Qwen runner's effective settings and gateway output limit.

Run with --docker or --kind after test_qwen.py has registered local-qwen.
The probe runs inside the Keeplane app container so neither model nor gateway
needs a host port. The kind path refuses any context other than kind-keeplane.
"""

import argparse
import json
import os
import subprocess
import sys


KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")
PROMPT = "Write the integers from 1 to 500, separated by commas. Output only the integers."
PROBE = r'''
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

gateway = sys.argv[1]
prompt = sys.argv[2]
runner = "http://qwen:8080"

def get(path):
    with urlopen(runner + path, timeout=10) as response:
        return json.load(response)

def completion(url, model):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "ignore_eos": True}).encode()
    request = Request(url + "/v1/chat/completions", data=body,
                      headers={"Content-Type": "application/json"})
    if url == gateway:
        key = Path(os.environ["GATEWAY_RUNTIME_KEY_FILE"]).read_text().strip()
        request.add_header("Authorization", "Bearer " + key)
    # The case checks the output limit, not latency. Shared local CPU can take
    # over two minutes to emit 256 tokens while Docker and kind run together.
    with urlopen(request, timeout=300) as response:
        result = json.load(response)
    choice = result["choices"][0]
    return {"completion_tokens": result["usage"]["completion_tokens"],
            "finish_reason": choice["finish_reason"],
            "answer_tail": choice["message"].get("content", "")[-80:]}

props = get("/props")["default_generation_settings"]
model = get("/v1/models")["data"][0]
print(json.dumps({
    "model": model["id"],
    "active_context": props["n_ctx"],
    "training_context": model["meta"]["n_ctx_train"],
    "temperature": props["params"]["temperature"],
    "top_p": props["params"]["top_p"],
    "props_default_max_tokens": props["params"]["max_tokens"],
    "direct": completion(runner, "qwen2.5-coder:0.5b"),
    "through_gateway": completion(gateway, "local-qwen"),
}))
'''


def main():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--docker", action="store_true")
    target.add_argument("--kind", action="store_true")
    args = parser.parse_args()

    if args.kind:
        context = subprocess.check_output(
            ["kubectl", "--kubeconfig", KUBECONFIG, "config", "current-context"], text=True
        ).strip()
        if context != "kind-keeplane":
            raise SystemExit(f"Refusing Kubernetes context {context!r}; expected kind-keeplane")
        command = ["kubectl", "--kubeconfig", KUBECONFIG, "-n", "keeplane", "exec",
                   "deploy/keeplane-app", "--", "python", "-c", PROBE,
                   "http://keeplane:4000", PROMPT]
    else:
        command = ["docker", "compose", "--profile", "qwen", "exec", "-T", "app",
                   "python", "-c", PROBE, "http://gateway:4000", PROMPT]

    observed = json.loads(subprocess.check_output(command, text=True, timeout=660))
    runtime_ok = (observed["model"] == "qwen2.5-coder:0.5b"
                  and observed["active_context"] == 4096
                  and observed["training_context"] == 32768
                  and abs(observed["temperature"] - 0.8) < 0.001
                  and abs(observed["top_p"] - 0.95) < 0.001)
    limit_ok = all(observed[path]["completion_tokens"] == 256
                   and observed[path]["finish_reason"] == "length"
                   for path in ("direct", "through_gateway"))
    result = {"suite": "Keeplane model runtime", "environment": "kind" if args.kind else "docker",
              "results": [
                  {"case": "LOCAL-19", "verdict": "pass" if runtime_ok else "fail",
                   "observed": {key: observed[key] for key in ("model", "active_context",
                               "training_context", "temperature", "top_p",
                               "props_default_max_tokens")}},
                  {"case": "LOCAL-20", "verdict": "pass" if limit_ok else "fail",
                   "observed": {key: observed[key] for key in ("direct", "through_gateway")}},
              ]}
    print(json.dumps(result, indent=2))
    return 0 if runtime_ok and limit_ok else 1


if __name__ == "__main__":
    sys.exit(main())
