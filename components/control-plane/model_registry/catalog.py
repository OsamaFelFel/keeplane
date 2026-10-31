"""Only Keeplane approvals live here; the gateway remains the model registry."""

from common.errors import GatewayRemovalFailed
from common.storage import settings_change, storage_service
from data_classes.models import DataClass
from django.db.models import Exists, OuterRef

from .levels import LEVEL_NAMES, LevelError, ModelInUse, describe_level_change
from .models import (
    ComplexityLevelChoice,
    DeveloperProviderKey,
    ModelApproval,
    ProviderKeyChoice,
)


def _names(values):
    return ", ".join(values) or "none"


def describe_model_change(model_id, previous, values, shared_key_replaced=False):
    """Say what an admin changed, naming no key, key file or prompt."""
    if previous is None:
        return (
            f"Set up model {model_id}; provider key: {values['key_choice']}; "
            f"approved classes: {_names(values['approved_classes'])}"
        )
    changes = []
    if shared_key_replaced:
        changes.append("replaced the shared provider key")
    if previous["key_choice"] != values["key_choice"]:
        changes.append(
            f"provider key: {previous['key_choice']} to {values['key_choice']}"
        )
    if previous["approved_classes"] != values["approved_classes"]:
        changes.append(
            f"approved classes: {_names(previous['approved_classes'])} "
            f"to {_names(values['approved_classes'])}"
        )
    if (
        not shared_key_replaced
        and previous["gateway_fingerprint"] != values["gateway_fingerprint"]
    ):
        changes.append("approved its changed gateway definition")
    if previous["owned_by_keeplane"] != values["owned_by_keeplane"]:
        changes.append(
            "now set up by Keeplane"
            if values["owned_by_keeplane"]
            else "no longer set up by Keeplane"
        )
    if not changes:
        changes.append("set up again")
    return f"Changed model {model_id}: " + "; ".join(changes)


@storage_service
class DjangoModelCatalog:
    def __init__(self, audit):
        self.audit = audit

    def get(self, model_id):
        return (
            ModelApproval.objects.filter(pk=model_id)
            .values(
                "key_choice",
                "approved_classes",
                "gateway_fingerprint",
                "owned_by_keeplane",
            )
            .first()
        )

    def personal_key_count(self, model_id, expected_fingerprint):
        """Count current-bound active-owner registrations, returning no identities."""
        if (
            not isinstance(expected_fingerprint, str)
            or len(expected_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in expected_fingerprint)
        ):
            return 0
        current = ModelApproval.objects.filter(
            pk=OuterRef("model_id"),
            key_choice=ProviderKeyChoice.PERSONAL,
            gateway_fingerprint=expected_fingerprint,
        )
        return (
            DeveloperProviderKey.objects.filter(
                model_id=model_id,
                owner__is_active=True,
                validation_fingerprint=expected_fingerprint,
            )
            .exclude(key_name="")
            .filter(Exists(current))
            .count()
        )

    def approve(
        self,
        model_id,
        classes,
        gateway_fingerprint,
        actor=None,
        owned_by_keeplane=False,
        key_choice="none",
        shared_key_replaced=False,
        context_tokens=None,
    ):
        if key_choice not in ProviderKeyChoice.values:
            raise ValueError("Choose a supported provider key option")
        if context_tokens is not None and (
            type(context_tokens) is not int or context_tokens <= 0
        ):
            raise ValueError("The model's context window could not be verified")
        if (
            not isinstance(classes, list)
            or any(not isinstance(item, str) for item in classes)
            or len(classes) != len(set(classes))
        ):
            raise ValueError("Choose valid data classes")
        if not gateway_fingerprint:
            raise ValueError("The gateway model definition could not be verified")
        with settings_change():
            known = list(
                DataClass.objects.order_by("position", "name").values_list(
                    "name", flat=True
                )
            )
            if not set(classes).issubset(known):
                raise ValueError("Choose valid data classes")
            ordered = [name for name in known if name in classes]
            previous = self.get(model_id)
            values = {
                "key_choice": key_choice,
                "approved_classes": ordered,
                "gateway_fingerprint": gateway_fingerprint,
                "owned_by_keeplane": bool(owned_by_keeplane),
            }
            stored = dict(values)
            if context_tokens is not None:
                # Kept from setup to setup; only a runner's report changes it.
                stored["context_tokens"] = context_tokens
            ModelApproval.objects.update_or_create(pk=model_id, defaults=stored)
            if actor and previous != values:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    describe_model_change(
                        model_id, previous, values, shared_key_replaced
                    ),
                )
        return {
            "model_id": model_id,
            "key_choice": key_choice,
            "approved_classes": ordered,
            "owned_by_keeplane": bool(owned_by_keeplane),
        }

    def context_windows(self, model_ids):
        """The context window recorded for each model, None when unknown."""
        model_ids = list(model_ids)
        known = dict(
            ModelApproval.objects.filter(pk__in=model_ids).values_list(
                "model_id", "context_tokens"
            )
        )
        return {model_id: known.get(model_id) for model_id in model_ids}

    def level_choices(self):
        """Each level an admin changed, with the model they chose."""
        return dict(ComplexityLevelChoice.objects.values_list("level", "model_id"))

    def _levels_using(self, model_id):
        levels = set(
            ComplexityLevelChoice.objects.filter(model_id=model_id).values_list(
                "level", flat=True
            )
        )
        return [name for level, name in LEVEL_NAMES.items() if level in levels]

    def routing_uses(self, model_id):
        """Names of the admin-changed levels that use a model."""
        return self._levels_using(model_id)

    def change_level(self, level, model_id, set_up_model_ids, actor=None):
        """Store an admin's pick for a level, or None to use Keeplane's pick.

        set_up_model_ids are the models set up now with their current gateway
        definition; gateway-only models are never among them.
        """
        if level not in LEVEL_NAMES:
            raise LevelError(404, "Complexity level not found")
        if model_id is not None and (
            not isinstance(model_id, str) or model_id not in set_up_model_ids
        ):
            raise LevelError(400, "Choose a model that is set up")
        with settings_change():
            # Recheck under the settings lock that removal also takes.
            if (
                model_id is not None
                and not ModelApproval.objects.filter(pk=model_id).exists()
            ):
                raise LevelError(400, "Choose a model that is set up")
            previous = (
                ComplexityLevelChoice.objects.filter(pk=level)
                .values_list("model_id", flat=True)
                .first()
            )
            if previous == model_id:
                return {"level": level, "model_id": model_id, "changed": False}
            if model_id is None:
                ComplexityLevelChoice.objects.filter(pk=level).delete()
            else:
                ComplexityLevelChoice.objects.update_or_create(
                    pk=level, defaults={"model_id": model_id}
                )
            if actor:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    describe_level_change(level, previous, model_id),
                )
        return {"level": level, "model_id": model_id, "changed": True}

    def remove(self, model_id, actor=None, remove_from_gateway=None):
        """Remove an approval; with remove_from_gateway, commit only after it succeeds.

        A model that an admin-changed level uses is kept and ModelInUse is
        raised; Keeplane's own picks never block removal (D121).

        remove_from_gateway runs inside the settings transaction, after the
        approval deletion and its Audit record are written. A failed gateway
        answer raises GatewayRemovalFailed and rolls both back.
        """
        with settings_change():
            # Checked under the settings lock, so a level can't be changed to
            # this model while it is being removed.
            in_use = self._levels_using(model_id)
            if in_use:
                raise ModelInUse(model_id, in_use)
            removed = bool(ModelApproval.objects.filter(pk=model_id).delete()[0])
            if removed and actor:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    f"Removed model {model_id} from the gateway"
                    if remove_from_gateway
                    else f"Removed Keeplane setup for model {model_id}",
                )
            if removed and remove_from_gateway:
                status, result = remove_from_gateway()
                if status != 200:
                    raise GatewayRemovalFailed(status, result)
        return removed

