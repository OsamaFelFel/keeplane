"""Verify the local-runner Add model path described in LOCAL-21–23."""

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from protected_preview import login_if_protected


BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:13000")
PROTECTED = login_if_protected(BASE)
RUNNER = os.environ.get("KEEPLANE_RUNNER_URL", "http://qwen:8080")
MODEL = os.environ.get("KEEPLANE_EXPECTED_MODEL", "qwen2.5-coder:0.5b")
EXPECTED_ANSWER = os.environ.get("KEEPLANE_EXPECTED_ANSWER", "")


def call(path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    request = Request(BASE + path, data=payload,
                      headers={"Content-Type": "application/json"} if payload else {})
    try:
        with urlopen(request, timeout=90) as response:
            raw = response.read()
            return response.status, json.loads(raw) if path.startswith("/api/") else raw.decode()
    except HTTPError as error:
        return error.code, json.load(error)
    except (URLError, TimeoutError) as error:
        return 503, {"error": str(error)}


def main():
    results = []

    def check(case, passed, observed):
        results.append({"case": case, "verdict": "pass" if passed else "fail", "observed": observed})

    page_status, page = call("/")
    check("LOCAL-23", page_status == 200 and "agentgateway" not in page.lower()
          and "Try the connection" not in page
          and "The model gateway isn't answering" in page and "Try again" in page,
          {"page_status": page_status, "gateway_identity_visible": "agentgateway" in page.lower(),
           "try_panel_visible": "Try the connection" in page})

    discovery_status, discovery = call("/api/runners/models", {"address": RUNNER})
    check("LOCAL-21", discovery_status == 200 and MODEL in discovery.get("models", []),
          {"status": discovery_status, "models": discovery.get("models"), "error": discovery.get("error")})
    runtime = discovery.get("runtime", {}).get(MODEL, {})
    check("LOCAL-24", discovery_status == 200 and
          runtime.get("active_context_tokens") == 4096 and
          runtime.get("training_context_tokens") == 32768,
          {"status": discovery_status, "active_context_tokens": runtime.get("active_context_tokens"),
           "training_context_tokens": runtime.get("training_context_tokens")})

    if discovery_status == 200:
        add_status, added = call("/api/models", {
            "name": MODEL, "model": MODEL, "source": "runner", "address": RUNNER,
            **({"approved_classes": ["Public"]} if PROTECTED else {}),
        })
        list_status, ids = 0, []
        for delay in (0, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2):
            time.sleep(delay)
            list_status, catalog = call("/api/models")
            ids = [item["id"] for item in catalog.get("models", [])]
            if MODEL in ids:
                break
        if PROTECTED:
            current = next((item for item in catalog.get("models", []) if item["id"] == MODEL), {})
            if current and not current.get("approved"):
                call(f"/api/models/{MODEL}/setup", {"key_choice": "none",
                                                    "approved_classes": ["Public"]})
        answer_status, answer = call("/api/ask", {"model": MODEL, "prompt": "Reply OK."})
        value = answer.get("answer", "")
        check("LOCAL-21-ADD", add_status == 200 and list_status == 200 and MODEL in ids
              and answer_status == 200 and bool(value.strip())
              and (not EXPECTED_ANSWER or value == EXPECTED_ANSWER),
              {"add_status": add_status, "add_result": added, "listed": MODEL in ids,
               "answer_status": answer_status, "answer_excerpt": value[:120]})

    unknown = "not-served-by-runner"
    unknown_status, unknown_result = call("/api/models", {
        "name": unknown, "model": unknown, "source": "runner", "address": RUNNER,
        **({"approved_classes": ["Public"]} if PROTECTED else {}),
    })
    denied_status, denied = call("/api/models", {
        "name": "not-allowed-runner", "model": MODEL, "source": "runner",
        "address": "http://not-enabled.invalid:18080",
        **({"approved_classes": ["Public"]} if PROTECTED else {}),
    })
    catalog_status, catalog = call("/api/models")
    ids = [item["id"] for item in catalog.get("models", [])]
    check("LOCAL-22", unknown_status == 400 and denied_status == 400 and catalog_status == 200
          and unknown not in ids and "not-allowed-runner" not in ids,
          {"unknown_status": unknown_status, "unknown_error": unknown_result.get("error"),
           "denied_status": denied_status, "denied_error": denied.get("error"),
           "saved_unknown": unknown in ids, "saved_denied": "not-allowed-runner" in ids})

    print(json.dumps({"suite": "Keeplane local runner flow", "runner": RUNNER,
                      "results": results}, indent=2))
    return 1 if any(result["verdict"] == "fail" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
