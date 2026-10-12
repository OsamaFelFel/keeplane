"""Only Keeplane approvals live here; the gateway remains the model registry."""

from .models import DataClass, ModelApproval
from .storage import settings_change, storage_service


@storage_service
class DjangoModelCatalog:
    def __init__(self, audit):
        self.audit = audit

    def get(self, model_id):
        return ModelApproval.objects.filter(pk=model_id).values(
            "key_choice", "approved_classes", "gateway_fingerprint", "owned_by_keeplane").first()

    def approve(self, model_id, classes, gateway_fingerprint, actor=None,
                owned_by_keeplane=False, key_choice="none"):
        if key_choice not in ("none", "shared"):
            raise ValueError("Choose a supported provider key option")
        if not isinstance(classes, list) or any(not isinstance(item, str) for item in classes) or len(classes) != len(set(classes)):
            raise ValueError("Choose valid data classes")
        if not gateway_fingerprint:
            raise ValueError("The gateway model definition could not be verified")
        with settings_change():
            known = list(DataClass.objects.order_by("position", "name").values_list("name", flat=True))
            if not set(classes).issubset(known):
                raise ValueError("Choose valid data classes")
            ordered = [name for name in known if name in classes]
            previous = self.get(model_id)
            values = {"key_choice": key_choice, "approved_classes": ordered,
                      "gateway_fingerprint": gateway_fingerprint, "owned_by_keeplane": bool(owned_by_keeplane)}
            ModelApproval.objects.update_or_create(pk=model_id, defaults=values)
            if actor and previous != values:
                self.audit.record_in_transaction(None, "settings", *actor,
                    f"Set up model {model_id}; key choice: {key_choice}; approved classes: {', '.join(ordered)}")
        return {"model_id": model_id, "key_choice": key_choice, "approved_classes": ordered,
                "owned_by_keeplane": bool(owned_by_keeplane)}

    def remove(self, model_id, actor=None, gateway_removed=False):
        with settings_change():
            removed = bool(ModelApproval.objects.filter(pk=model_id).delete()[0])
            if removed and actor:
                self.audit.record_in_transaction(None, "settings", *actor,
                    f"Removed {'model' if gateway_removed else 'Keeplane setup for model'} {model_id}"
                    + (" from the gateway" if gateway_removed else ""))
        return removed
