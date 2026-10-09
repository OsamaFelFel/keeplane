"""Check compatibility without changing a supplied gateway's configuration."""

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


URL = os.environ.get("GATEWAY_URL", "").rstrip("/")
EXPECTED_VERSION = os.environ.get("EXPECTED_GATEWAY_VERSION", "")
MODEL = os.environ.get("GATEWAY_PREFLIGHT_MODEL", "")


def fetch(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = Request(URL + path, data=data, headers=headers)
    try:
        with urlopen(request, timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, None
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return 0, None


def check():
    if not URL.startswith(("http://", "https://")) or not EXPECTED_VERSION:
        return False, "Set a gateway URL and expected version"
    for attempt in range(3):
        status, runtime = fetch("/api/runtime")
        if status == 200 and isinstance(runtime, dict):
            break
        if attempt < 2:
            time.sleep(1)
    else:
        return False, "Gateway runtime API did not answer"
    version = runtime.get("build", {}).get("version") if isinstance(runtime.get("build"), dict) else None
    if version != EXPECTED_VERSION:
        return False, "Gateway version differs from the pinned integration version"
    status, listing = fetch("/v1/models")
    if status != 200 or not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
        return False, "Gateway model-list API is unavailable"
    status, resources = fetch("/api/config/resources/llm.model")
    if status != 200 or not isinstance(resources, dict) or not isinstance(resources.get("resources"), list):
        return False, "Gateway model-management read API is unavailable"
    if MODEL:
        if MODEL not in {item.get("id") for item in listing["data"] if isinstance(item, dict)}:
            return False, "Preflight model is absent from the gateway"
        status, answer = fetch("/v1/chat/completions", {
            "model": MODEL, "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": 1})
        if status != 200 or not isinstance(answer, dict) or not isinstance(answer.get("choices"), list) or \
                not answer["choices"]:
            return False, "Preflight model did not answer through the gateway"
    return True, "Existing gateway passed compatibility checks"


if __name__ == "__main__":
    passed, message = check()
    print(json.dumps({"passed": passed, "message": message,
                      "expected_version": EXPECTED_VERSION,
                      "inference_checked": bool(MODEL)}))
    sys.exit(0 if passed else 1)
