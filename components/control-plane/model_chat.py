"""Protected preview Ask use case; the gateway performs model transport."""

import time

from model_catalog import fingerprint


def ask_model(body, catalog, gateway, file_config):
    model = body.get("model")
    prompt = body.get("prompt")
    if not isinstance(model, str) or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
        return 400, {"error": "Choose a model and enter a prompt (up to 8000 characters)"}

    approval = catalog.get(model)
    if approval is None:
        return 403, {"error": "This model has not been set up for Keeplane"}
    status, registry = gateway.resources()
    if status != 200:
        return status, registry
    if approval["gateway_fingerprint"] != fingerprint(model, registry.get("resources", []), file_config):
        return 403, {"error": "This model changed in the gateway and must be set up again"}

    request_body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 64}
    status, result = gateway.request("/v1/chat/completions", request_body,
                                     connection_retries=3)
    # Another gateway replica may not have applied a registration yet. This
    # explicit not-found response has not reached a model and can be retried.
    if status == 404 and isinstance(result.get("error"), dict) and \
            result["error"].get("code") == "model_not_found":
        for delay in (0.1, 0.2, 0.4):
            time.sleep(delay)
            status, result = gateway.request("/v1/chat/completions", request_body,
                                             connection_retries=3)
            if status != 404 or not isinstance(result.get("error"), dict) or \
                    result["error"].get("code") != "model_not_found":
                break
    if status != 200:
        return status, result
    choice = result.get("choices", [{}])[0]
    return 200, {"model": model, "answer": choice.get("message", {}).get("content", "")}
