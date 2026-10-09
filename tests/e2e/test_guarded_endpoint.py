"""Run in the app container: docker compose exec -T app python - < tests/e2e/test_guarded_endpoint.py."""

import json
import os
import sys
import http.cookiejar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, install_opener, urlopen


APP = "http://127.0.0.1:3000"
PROVIDER = "http://guarded-provider:18081"
GATEWAY = "http://gateway:4000"
KEY = os.environ["PREVIEW_PROVIDER_KEY"]
MODEL = "guarded-qwen-e2e"
UPSTREAM = "qwen2.5-coder:0.5b"
RESULTS = []


def call(base, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(base + path, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def check(case, passed, observed):
    RESULTS.append({"case": case, "verdict": "pass" if passed else "fail", "observed": observed})


def main():
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("X-Keeplane-Action", "1")]
    credential = Path("/run/secrets/first-admin-password").read_text().strip()
    request = Request(APP + "/api/session", method="POST",
                      data=json.dumps({"username": "first-admin", "password": credential}).encode(),
                      headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("Admin sign-in failed")
    install_opener(opener)
    prompt = {"model": UPSTREAM, "messages": [{"role": "user", "content": "Reply with OK."}],
              "max_tokens": 32}
    no_key, _ = call(PROVIDER, "/v1/chat/completions", prompt)
    wrong_key, _ = call(PROVIDER, "/v1/chat/completions", prompt,
                        {"Authorization": "Bearer invalid-trial-key"})
    check("LOCAL-12", no_key == 401 and wrong_key == 401,
          {"without_key": no_key, "wrong_key": wrong_key})

    registered, saved = call(APP, "/api/models", {"name": MODEL, "model": UPSTREAM,
                                                "source": "guarded", "approved_classes": ["Public"]})
    models_status, models = call(APP, "/api/models")
    entry = next((item for item in models.get("models", []) if item.get("id") == MODEL), {})
    management_status, management = call(GATEWAY, "/api/config/resources/llm.model")
    managed = next((item.get("value", {}) for item in management.get("resources", [])
                    if item.get("id") == MODEL), {})
    has_key = managed.get("auth", {}).get("key", {}).get("value") == KEY
    catalog_hides_key = KEY not in json.dumps(models)
    check("LOCAL-13", registered == 200 and models_status == 200 and management_status == 200
          and entry.get("kind") == "endpoint-trial" and has_key and catalog_hides_key,
          {"register_status": registered, "existing": saved.get("existing", False),
           "model_kind": entry.get("kind"), "management_status": management_status,
           "gateway_has_trial_key": has_key, "ui_catalog_hides_key": catalog_hides_key})

    if entry and not entry.get("approved"):
        call(APP, f"/api/models/{MODEL}/setup", {"key_choice": "shared",
                                                  "approved_classes": ["Public"]})
    ask_status, answer = call(APP, "/api/ask", {"model": MODEL, "prompt": "Reply with exactly: guarded route works"})
    check("LOCAL-14", ask_status == 200 and answer.get("model") == MODEL
          and bool(answer.get("answer", "").strip()),
          {"status": ask_status, "model": answer.get("model"),
           "has_generated_text": bool(answer.get("answer", "").strip())})

    repeat, repeated = call(APP, "/api/models", {"name": MODEL, "model": UPSTREAM,
                                                "source": "guarded", "approved_classes": ["Public"]})
    conflict, _ = call(APP, "/api/models", {"name": MODEL, "model": "other",
                                          "source": "guarded", "approved_classes": ["Public"]})
    check("LOCAL-15", repeat == 200 and repeated.get("existing") is True and conflict == 409,
          {"repeat_status": repeat, "repeat_existing": repeated.get("existing"),
           "conflict_status": conflict})

    print(json.dumps({"suite": "guarded endpoint trial", "results": RESULTS}, indent=2))
    return 1 if any(item["verdict"] != "pass" for item in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
