"""Run the repeatable, dependency-free part of cases.md against local Docker."""

import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from protected_preview import login_if_protected


BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:3000")
PROTECTED = login_if_protected(BASE)


def call(path, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(BASE + path, data=data, method=method,
                      headers={"Content-Type": "application/json"} if data else {})
    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, json.loads(raw) if path.startswith("/api/") or path == "/health" else raw.decode()
    except HTTPError as error:
        return error.code, json.loads(error.read())


def main():
    results = []

    def check(case, okay, observed):
        results.append({"case": case, "verdict": "pass" if okay else "fail", "observed": observed})

    status, page = call("/")
    health, state = call("/health")
    with urlopen(BASE + "/fonts/IBMPlexSans-Regular.woff2", timeout=10) as font:
        font_status, font_signature = font.status, font.read(4)
    check("LOCAL-01", status == 200 and "Models and routing" in page and health == 200
          and font_status == 200 and font_signature == b"wOF2",
          {"page_status": status, "health": state, "local_font_status": font_status})

    status, catalog = call("/api/models")
    models = {item["id"]: item for item in catalog.get("models", [])}
    check("LOCAL-02", status == 200 and models.get("local-fixture", {}).get("kind") == "fixture",
          {"status": status, "models": list(models)})

    if PROTECTED and not models["local-fixture"]["approved"]:
        call("/api/models/local-fixture/setup", {"key_choice": "none",
             "approved_classes": ["Public"]})
    status, answer = call("/api/ask", {"model": "local-fixture", "prompt": "fixture"})
    check("LOCAL-03", status == 200 and answer.get("answer") == "mock answer",
          {"status": status, "model": answer.get("model"), "answer": answer.get("answer")})

    status, saved = call("/api/models", {"name": "second-local", "model": "mock-local",
                                          **({"approved_classes": ["Public"]} if PROTECTED else {})})
    listed_status, listed = call("/api/models")
    second = next((item for item in listed.get("models", []) if item["id"] == "second-local"), None)
    if PROTECTED and second and not second["approved"]:
        call("/api/models/second-local/setup", {"key_choice": "none",
             "approved_classes": ["Public"]})
    ask_status, second = call("/api/ask", {"model": "second-local", "prompt": "fixture"})
    listed_models = {item["id"]: item for item in listed.get("models", [])}
    check("LOCAL-04", status == 200 and listed_status == 200 and "second-local" in listed_models
          and ask_status == 200 and second.get("answer") == "mock answer",
          {"register_status": status, "register_result": saved,
           "listed": list(listed_models), "ask_status": ask_status})

    status, denied = call("/api/ask", {"model": "not-registered", "prompt": "fixture"})
    check("LOCAL-05", status == (403 if PROTECTED else 404),
          {"status": status, "error": denied.get("error")})

    gateway_status, identity = call("/api/status")
    fixture = listed_models.get("second-local", {})
    check("LOCAL-08", gateway_status == 200 and identity.get("gateway", {}).get("name") == "agentgateway"
          and identity.get("gateway", {}).get("version") == "1.6.0"
          and fixture.get("kind") == "fixture",
          {"gateway": identity.get("gateway"), "fixture": fixture})

    classes = {"approved_classes": ["Public"]} if PROTECTED else {}
    repeat_status, repeat = call("/api/models", {"name": "second-local", "model": "mock-local", **classes})
    conflict_status, conflict = call("/api/models", {"name": "second-local", "model": "another-model", **classes})
    still_status, still = call("/api/ask", {"model": "second-local", "prompt": "fixture"})
    check("LOCAL-11", repeat_status == 200 and repeat.get("existing") is True
          and conflict_status == 409 and still_status == 200 and still.get("answer") == "mock answer",
          {"repeat_status": repeat_status, "conflict_status": conflict_status,
           "conflict": conflict.get("error"), "answer_after_conflict": still.get("answer")})

    if PROTECTED:
        for model_id in ("local-fixture", "second-local"):
            if not models.get(model_id, {}).get("approved"):
                call(f"/api/models/{model_id}/setup", {}, method="DELETE")

    print(json.dumps({"suite": "Keeplane local model slice", "results": results}, indent=2))
    return 1 if any(item["verdict"] != "pass" for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
