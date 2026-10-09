"""Run LOCAL-07 after starting the optional real Qwen runner."""

import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from protected_preview import login_if_protected


BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:3000")
PROTECTED = login_if_protected(BASE)


def post(path, body):
    request = Request(BASE + path, data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=180) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def get(path):
    with urlopen(BASE + path, timeout=10) as response:
        return response.status, json.load(response)


def main():
    created, _ = post("/api/models", {"name": "local-qwen", "source": "qwen",
                                      "model": "qwen2.5-coder:0.5b",
                                      **({"approved_classes": ["Public"]} if PROTECTED else {})})
    if PROTECTED:
        _, before = get("/api/models")
        current = next((item for item in before.get("models", []) if item.get("id") == "local-qwen"), {})
        if current and not current.get("approved"):
            post("/api/models/local-qwen/setup", {"key_choice": "none",
                                                  "approved_classes": ["Public"]})
    status, result = post("/api/ask", {"model": "local-qwen", "prompt": "Write a Python function that adds two integers. Return code only."})
    answer = result.get("answer", "")
    passed = created == 200 and status == 200 and bool(answer.strip()) and answer != "mock answer"
    listed_status, catalog = get("/api/models")
    qwen = next((item for item in catalog.get("models", []) if item.get("id") == "local-qwen"), {})
    identified = (listed_status == 200 and qwen.get("kind") == "real-local"
                  and qwen.get("provider") == "Qwen Coder via llama.cpp"
                  and qwen.get("upstream_model") == "qwen2.5-coder:0.5b")
    print(json.dumps({"suite": "Keeplane real local model", "results": [
        {"case": "LOCAL-07", "verdict": "pass" if passed else "fail",
         "observed": {"register_status": created, "answer_status": status,
                      "model": result.get("model"), "answer_excerpt": answer[:400],
                      "error": result.get("error")}},
        {"case": "LOCAL-09", "verdict": "pass" if identified else "fail",
         "observed": {"model": qwen}},
    ]}, indent=2))
    return 0 if passed and identified else 1


if __name__ == "__main__":
    sys.exit(main())
