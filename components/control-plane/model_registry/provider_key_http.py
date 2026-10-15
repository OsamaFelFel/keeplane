"""Owned validation worker. Secrets arrive only on stdin; output is discarded."""

import json
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def valid_personal_key(value):
    return (
        isinstance(value, str)
        and 12 <= len(value) <= 512
        and all(33 <= ord(char) <= 126 for char in value)
    )


def check(config):
    provider, key = config["provider"], config["key"]
    if not valid_personal_key(key):
        return 2
    body = {
        "model": config["model"],
        "messages": [{"role": "user", "content": "Reply OK."}],
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if provider == "openAI":
        body["max_completion_tokens"] = 1
        headers["Authorization"] = "Bearer " + key
    elif provider == "anthropic":
        body["max_tokens"] = 1
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        return 2
    request = Request(
        config["url"], data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(
            request, timeout=8
        ) as response:
            if response.status != 200:
                return 2
            raw = response.read(65537)
            if len(raw) > 65536:
                return 2
            answer = json.loads(raw)
    except HTTPError as error:
        error.close()
        return 1 if error.code in (401, 403) else 2
    if provider == "openAI":
        choices = answer.get("choices")
        return (
            0
            if isinstance(choices, list)
            and choices
            and isinstance(choices[0].get("message"), dict)
            else 2
        )
    return (
        0
        if answer.get("type") == "message" and isinstance(answer.get("content"), list)
        else 2
    )


if __name__ == "__main__":
    try:
        result = check(json.loads(sys.stdin.buffer.read(8193)))
    except Exception:
        result = 2
    sys.exit(result)
