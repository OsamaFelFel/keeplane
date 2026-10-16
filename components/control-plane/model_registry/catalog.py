"""Only Keeplane approvals live here; the gateway remains the model registry."""

from common.storage import settings_change, storage_service
from data_classes.models import DataClass
from django.db.models import Exists, OuterRef

from .models import DeveloperProviderKey, ModelApproval, ProviderKeyChoice


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
    ):
        if key_choice not in ProviderKeyChoice.values:
            raise ValueError("Choose a supported provider key option")
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
            ModelApproval.objects.update_or_create(pk=model_id, defaults=values)
            if actor and previous != values:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    f"Set up model {model_id}; key choice: {key_choice}; approved classes: {', '.join(ordered)}",
                )
        return {
            "model_id": model_id,
            "key_choice": key_choice,
            "approved_classes": ordered,
            "owned_by_keeplane": bool(owned_by_keeplane),
        }

    def remove(self, model_id, actor=None, gateway_removed=False):
        with settings_change():
            removed = bool(ModelApproval.objects.filter(pk=model_id).delete()[0])
            if removed and actor:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    f"Removed {'model' if gateway_removed else 'Keeplane setup for model'} {model_id}"
                    + (" from the gateway" if gateway_removed else ""),
                )
        return removed
