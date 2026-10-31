"""Remove Keeplane model setup without deleting customer-owned gateway models."""

from common.errors import GatewayRemovalFailed, StorageUnavailable
from model_registry.fingerprints import fingerprint
from model_registry.levels import ModelInUse
from integrations.gateway.copies import GatewayCopies
from integrations.gateway.keys import (
    from_resource as provider_key_file,
    remove as remove_provider_key,
)

NOT_RECORDED = "Keeplane couldn't record the removal. "
RESTORE_OUTCOMES = {
    "restored": "The model is back in the gateway and nothing changed.",
    "restored_personal": "The model is back in the gateway. Developers using "
    "their own provider keys for it must check them again.",
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
    # Personal keys are checked against one gateway revision; the new one
    # does not match them until each developer checks their key again.
    return "restored_personal" if approval["key_choice"] == "personal" else "restored"


NOT_GONE_EVERYWHERE = (
    "Model removed from Keeplane, so developers can't use it, but not every "
    "gateway copy confirmed it's gone. {summary} Check the gateway."
)


def _removed(model_id, approval, resource, provider_key_dir, copies, file_config):
    # The approval is already gone, and every copy's checks read it, so the
    # model is refused everywhere before this readback. The shared key file is
    # removed even when a copy still lists the model: that copy then has no
    # key to use.
    key_removed = approval["key_choice"] != "shared" or remove_provider_key(
        provider_key_dir, provider_key_file(resource)
    )
    readback = copies.confirm(model_id, None, file_config)
    if not readback.complete:
        return 503, {"error": NOT_GONE_EVERYWHERE.format(summary=readback.summary())}
    if not key_removed:
        return 503, {"error": "Model removed, but its shared key file needs cleanup"}
    return 200, {"removed_from_keeplane": True, "gateway_model_preserved": False}


def remove_model_setup(
    model_id, actor, catalog, gateway, file_config, provider_key_dir, copies=None
):
    copies = copies if copies is not None else GatewayCopies([])
    approval = catalog.get(model_id)
    if approval is None:
        return 404, {"error": "Model setup not found"}
    # A level an admin changed or a persona rule keeps its model (Spec 004
    # ST23, D121). This early answer sends nothing to the gateway;
    # catalog.remove checks again under the settings lock.
    in_use = catalog.routing_uses(model_id)
    if in_use["levels"] or in_use["persona_rules"]:
        return 409, ModelInUse(model_id, **in_use).body()
    if not approval["owned_by_keeplane"]:
        try:
            removed = catalog.remove(model_id, actor)
        except ModelInUse as error:
            return 409, error.body()
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
    except ModelInUse as error:
        # Raised before the gateway step, so nothing was deleted.
        return 409, error.body()
    except StorageUnavailable:
        if not deleted:
            raise
        # The gateway deletion succeeded but the commit reported a failure.
        try:
            current = catalog.get(model_id)
        except StorageUnavailable:
            current = approval  # Unknown: keep the model rather than lose it.
        if current is None:
            # The commit landed even though it reported a failure.
            return _removed(
                model_id, approval, resource, provider_key_dir, copies, file_config
            )
        if current != approval:
            # Someone changed the setup since; writing back could undo that.
            return 503, {"error": NOT_RECORDED + RESTORE_OUTCOMES["missing"]}
        outcome = _restore(model_id, approval, resource, catalog, gateway, file_config)
        return 503, {"error": NOT_RECORDED + RESTORE_OUTCOMES[outcome]}
    if not removed:
        # Another request removed it first; this one deleted nothing.
        return 404, {"error": "Model setup not found"}
    return _removed(
        model_id, approval, resource, provider_key_dir, copies, file_config
    )
