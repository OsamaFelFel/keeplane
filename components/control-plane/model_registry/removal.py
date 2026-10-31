"""Remove Keeplane model setup without deleting customer-owned gateway models."""

from common.errors import GatewayRemovalFailed, StorageUnavailable
from model_registry.fingerprints import fingerprint
from integrations.gateway.keys import (
    from_resource as provider_key_file,
    remove as remove_provider_key,
)

NOT_RECORDED = "Keeplane couldn't record the removal. "
RESTORE_OUTCOMES = {
    "restored": "The model is back in the gateway and nothing changed.",
    "unpinned": "The model is back in the gateway; check its setup in Models.",
    "missing": "The model may be missing from the gateway; check Models.",
}


def _restore(model_id, approval, resource, catalog, gateway, file_config):
    """Put back a deleted Keeplane-owned definition and re-pin its approval.

    The restored definition has a new gateway revision, so the unchanged
    approval is bound to it again. This is a rollback, not an admin change,
    so it writes no Audit record. Returns a RESTORE_OUTCOMES key.
    """
    status, _ = gateway.restore_model(resource)
    if status != 200:
        return "missing"
    status, registry = gateway.resources()
    if status != 200:
        return "unpinned"
    raw = registry.get("resources", [])
    current = next(
        (item.get("value") for item in raw if item.get("id") == model_id), None
    )
    revision = fingerprint(model_id, raw, file_config)
    if current != resource or not revision:
        return "unpinned"
    try:
        catalog.approve(
            model_id,
            approval["approved_classes"],
            revision,
            None,
            owned_by_keeplane=True,
            key_choice=approval["key_choice"],
        )
    except (ValueError, StorageUnavailable):
        return "unpinned"
    return "restored"


def remove_model_setup(
    model_id, actor, catalog, gateway, file_config, provider_key_dir
):
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
    resource = next(
        (item.get("value", {}) for item in raw_resources if item.get("id") == model_id),
        {},
    )
    if (
        fingerprint(model_id, raw_resources, file_config)
        != approval["gateway_fingerprint"]
    ):
        return 409, {
            "error": "The model changed in the gateway. "
            "Keeplane will not remove a changed definition."
        }

    deleted = []

    def remove_from_gateway():
        # Runs after the approval deletion and its Audit record are written
        # but before they commit, so a refused deletion changes nothing.
        status, result = gateway.delete_model(model_id)
        if status == 200:
            deleted.append(model_id)
        return status, result

    try:
        removed = catalog.remove(
            model_id, actor, remove_from_gateway=remove_from_gateway
        )
    except GatewayRemovalFailed as refused:
        return refused.status, refused.result
    except StorageUnavailable:
        if not deleted:
            raise
        # The gateway deletion succeeded but the commit did not.
        outcome = _restore(model_id, approval, resource, catalog, gateway, file_config)
        return 503, {"error": NOT_RECORDED + RESTORE_OUTCOMES[outcome]}
    if not deleted:
        # Another request removed the approval first; nothing was deleted here.
        return 200, {"removed_from_keeplane": removed, "gateway_model_preserved": True}
    if approval["key_choice"] == "shared" and not remove_provider_key(
        provider_key_dir, provider_key_file(resource)
    ):
        return 503, {"error": "Model removed, but its shared key file needs cleanup"}
    return 200, {"removed_from_keeplane": removed, "gateway_model_preserved": False}
