"""Remove Keeplane model setup without deleting customer-owned gateway models."""

from model_catalog import fingerprint
from provider_keys import from_resource as provider_key_file, remove as remove_provider_key


def remove_model_setup(model_id, actor, catalog, gateway, file_config, provider_key_dir):
    approval = catalog.get(model_id)
    if approval is None:
        return 404, {"error": "Model setup not found"}
    if not approval["owned_by_keeplane"]:
        removed = catalog.remove(model_id, actor)
        return 200, {"removed_from_keeplane": removed, "gateway_model_preserved": True}

    status, registry = gateway.resources()
    if status != 200:
        return status, registry
    raw_resources = registry.get("resources", [])
    resource = next((item.get("value", {}) for item in raw_resources
                     if item.get("id") == model_id), {})
    if fingerprint(model_id, raw_resources, file_config) != approval["gateway_fingerprint"]:
        return 409, {"error": "The model changed in the gateway. "
                              "Keeplane will not remove a changed definition."}
    status, result = gateway.delete_model(model_id)
    if status != 200:
        return status, result
    removed = catalog.remove(model_id, actor, gateway_removed=True)
    if approval["key_choice"] == "shared" and not remove_provider_key(
            provider_key_dir, provider_key_file(resource)):
        return 503, {"error": "Model removed, but its shared key file needs cleanup"}
    return 200, {"removed_from_keeplane": removed, "gateway_model_preserved": False}
