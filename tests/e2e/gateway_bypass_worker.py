"""Run inside a disposable sibling workload with no Keeplane credential."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


gateway = os.environ["GATEWAY_BASE"].rstrip("/")
model_service = os.environ["MODEL_BASE"].rstrip("/")
model = os.environ["MODEL_NAME"]


def request(url, payload=None, headers=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(req, timeout=15) as response:
            raw = response.read()
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            return response.status, data
    except HTTPError as error:
        try:
            data = json.load(error)
        except ValueError:
            data = {}
        return error.code, data


before = request(model_service + "/calls")[1]["count"]
listing = request(gateway + "/v1/models")
management = request(gateway + "/api/config/resources/llm.model")
key_management = request(gateway + "/api/config/resources/llm.apiKey")
runtime_info = request(gateway + "/api/runtime")
body = {"model": model, "messages": [{"role": "user", "content": "bypass trial"}],
        "max_tokens": 4}
direct = request(gateway + "/v1/chat/completions", body)
forged = request(gateway + "/v1/chat/completions", body, {
    "Authorization": "Bearer invalid-credential",
    "X-Keeplane-User": "first-admin",
    "X-Keeplane-Role": "admin",
    "X-Keeplane-Project": "other-project",
    "X-Keeplane-Class": "Public",
})
stream = request(gateway + "/v1/chat/completions", {**body, "stream": True})
tools = request(gateway + "/v1/chat/completions", {**body, "tools": [{"type": "function",
    "function": {"name": "probe", "parameters": {"type": "object", "properties": {}}}}]})
responses = request(gateway + "/v1/responses", {"model": model, "input": "bypass trial"})
messages = request(gateway + "/v1/messages", {"model": model, "max_tokens": 4,
    "messages": [{"role": "user", "content": "bypass trial"}]})
after = request(model_service + "/calls")[1]["count"]
print(json.dumps({
    "model_list_status": listing[0],
    "management_read_status": management[0],
    "key_management_read_status": key_management[0],
    "runtime_info_status": runtime_info[0],
    "direct_chat_status": direct[0],
    "forged_chat_status": forged[0],
    "stream_status": stream[0],
    "tools_status": tools[0],
    "responses_status": responses[0],
    "messages_status": messages[0],
    "upstream_calls_added": after - before,
    "model": model,
}))
