"""Owned no-credential HTTP worker; discard provider bodies and diagnostics."""

import json
import sys
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check(config):
    provider = config["provider"]
    body = {
        "model": config["model"],
        "messages": [{"role": "user", "content": "Reply OK."}],
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if provider == "openAI":
        body["max_completion_tokens"] = 1
    elif provider == "anthropic":
        body["max_tokens"] = 1
        headers["anthropic-version"] = "2023-06-01"
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
            return 0 if len(raw) <= 65536 and isinstance(json.loads(raw), dict) else 2
    except HTTPError as error:
        error.close()
        return 0 if error.code in (401, 403) else 2


if __name__ == "__main__":
    try:
        result = check(json.loads(sys.stdin.buffer.read(8193)))
    except (HTTPException, KeyError, OSError, TypeError, ValueError):
        result = 2
    sys.exit(result)
