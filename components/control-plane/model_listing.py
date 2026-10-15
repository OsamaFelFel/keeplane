"""Keeplane's model-listing use case, independent of gateway HTTP transport."""

from model_catalog import fingerprint


def model_details(model_id, resources, runner_urls):
    # The local fixture is file-owned and absent from the resource API.
    if model_id == "local-fixture":
        return {"id": model_id, "provider": "Test fixture", "kind": "fixture",
                "upstream_model": "mock-local"}

    resource = resources.get(model_id, {})
    params = resource.get("params", {})
    provider = resource.get("provider")
    if provider in ("openAI", "anthropic"):
        return {"id": model_id, "provider": "OpenAI" if provider == "openAI" else "Anthropic",
                "kind": "cloud", "upstream_model": params.get("model")}
    source = params.get("baseUrl")
    if source == "http://qwen:8080/v1":
        return {"id": model_id, "provider": "Qwen Coder via llama.cpp", "kind": "real-local",
                "upstream_model": params.get("model")}
    if source == "http://guarded-provider:18081/v1":
        return {"id": model_id, "provider": "Guarded endpoint trial (Qwen)", "kind": "endpoint-trial",
                "upstream_model": params.get("model")}
    if source == "http://model:18080/v1":
        return {"id": model_id, "provider": "Test fixture", "kind": "fixture",
                "upstream_model": params.get("model")}
    if isinstance(source, str) and source.endswith("/v1") and source[:-3] in runner_urls:
        return {"id": model_id, "provider": "Local runner", "kind": "real-local",
                "upstream_model": params.get("model")}
    return {"id": model_id, "provider": "Unknown source", "kind": "unknown",
            "upstream_model": params.get("model")}


def list_models(get_models, get_resources, catalog, file_config, runner_urls):
    """Join the gateway's live registry with Keeplane's small approval catalog."""
    status, listing = get_models()
    if status != 200:
        return status, listing
    status, registry = get_resources()
    if status != 200:
        return status, registry
    raw_resources = registry.get("resources", [])
    resources = {item["id"]: item.get("value", {})
                 for item in raw_resources if "id" in item}
    models = []
    for item in listing.get("data", []):
        model_id = item.get("id")
        if not model_id:
            continue
        details = model_details(model_id, resources, runner_urls)
        if catalog:
            approval = catalog.get(model_id)
            if approval and approval["gateway_fingerprint"] != fingerprint(
                    model_id, raw_resources, file_config):
                approval = None
            details.update({"approved": approval is not None,
                            "key_choice": approval["key_choice"] if approval else None,
                            "approved_classes": approval["approved_classes"] if approval else [],
                            "owned_by_keeplane": approval["owned_by_keeplane"] if approval else False})
        models.append(details)
    return 200, {"models": models}
