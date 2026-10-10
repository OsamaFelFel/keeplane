"""Allowlisted local model discovery and answer verification."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRunnerRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None

RUNNER_OPENER = build_opener(NoRunnerRedirect)


def local_runner(address, allowed_urls, model=None):
    """Inspect an explicitly allowed runner without following redirects."""
    address = address.rstrip("/") if isinstance(address, str) else ""
    if address not in allowed_urls:
        return 400, {"error": "This runner address is not enabled in the local preview"}
    try:
        with RUNNER_OPENER.open(address + "/v1/models", timeout=10) as response:
            listing = json.load(response)
        if not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
            raise ValueError("Invalid model list")
        served = listing["data"]
        names = [item.get("id") for item in served if isinstance(item, dict) and isinstance(item.get("id"), str)]
        if model is None:
            runtime = {}
            # llama.cpp exposes the loaded instance's effective context in
            # /props. Its model metadata reports a different training limit.
            # Only attribute the instance setting when it serves one model.
            if len(names) == 1:
                try:
                    with RUNNER_OPENER.open(address + "/props", timeout=2) as response:
                        props = json.load(response)
                    active = props.get("default_generation_settings", {}).get("n_ctx")
                    if type(active) is int and active > 0:
                        runtime[names[0]] = {"active_context_tokens": active}
                        matching = next(item for item in served if isinstance(item, dict)
                                        and item.get("id") == names[0])
                        metadata = matching.get("meta", {})
                        training = metadata.get("n_ctx_train") if isinstance(metadata, dict) else None
                        if type(training) is int and training > 0:
                            runtime[names[0]]["training_context_tokens"] = training
                except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError,
                        AttributeError, TypeError):
                    pass  # Discovery still works for runners without /props.
            return 200, {"models": names, "runtime": runtime}
        if model not in names:
            return 400, {"error": f"{model} is not served by the runner at {address}"}
        probe = Request(address + "/v1/chat/completions", method="POST",
                        data=json.dumps({"model": model, "messages": [{"role": "user", "content": "Reply OK."}],
                                         "max_tokens": 1}).encode(),
                        headers={"Content-Type": "application/json"})
        with RUNNER_OPENER.open(probe, timeout=30) as response:
            checked = json.load(response)
        if not isinstance(checked, dict) or not isinstance(checked.get("choices"), list) or not checked["choices"]:
            raise ValueError("No completion choice")
        choice = checked["choices"][0]
        if not isinstance(choice, dict):
            raise ValueError("Invalid completion choice")
        message = choice.get("message", {})
        if not isinstance(message, dict) or not isinstance(message.get("content"), str) or not message["content"].strip():
            raise ValueError("No model answer")
        return 200, {"models": names}
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return 503, {"error": f"The runner at {address} didn't answer."}
