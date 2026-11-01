"""Data-class settings and model approvals in Django transactions."""

import uuid
from django.db.models import Count, Max

from .contracts import DETECTION_DEFAULT, DataClassError, STARTERS
from .models import DataClass, ProjectClass, Settings
from model_registry.models import ModelApproval
from common.storage import settings_change, storage_service


@storage_service
class DjangoDataClassStore:
    def __init__(self, audit):
        self.audit = audit

    def _rows(self):
        return list(
            DataClass.objects.order_by("position", "name").values_list("id", "name")
        )

    def _approvals(self):
        return list(
            ModelApproval.objects.order_by("model_id").values_list(
                "model_id", "approved_classes"
            )
        )

    def enabled(self):
        return Settings.objects.filter(pk=1, classes_enabled=True).exists()

    def _require_enabled(self):
        if not self.enabled():
            raise DataClassError(409, "Turn on data classes first")

    def set_enabled(self, enabled, actor=None):
        if type(enabled) is not bool:
            raise DataClassError(400, "Choose whether to use data classes")
        with settings_change() as settings:
            starters = enabled and not DataClass.objects.exists()
            if starters:
                DataClass.objects.bulk_create(
                    [
                        DataClass(id=identifier, name=name, position=position)
                        for position, (identifier, name) in enumerate(STARTERS)
                    ]
                )
            if settings.classes_enabled != enabled:
                settings.classes_enabled = enabled
                settings.save(update_fields=["classes_enabled"])
                if actor:
                    self.audit.record_in_transaction(
                        "settings",
                        *actor,
                        "Turned data classes "
                        + ("on" if enabled else "off")
                        + (
                            "; added starter classes: "
                            + ", ".join(name for _, name in STARTERS)
                            if starters
                            else ""
                        ),
                    )
        return {"enabled": enabled}

    def detection(self):
        """Personal-data detection settings (Spec 005 ST20); off by default."""
        settings = Settings.objects.filter(pk=1).values(
            "detection_enabled", "detection_class_id"
        ).first() or {"detection_enabled": False, "detection_class_id": None}
        class_id = settings["detection_class_id"]
        if class_id is None and DataClass.objects.filter(pk=DETECTION_DEFAULT).exists():
            class_id = DETECTION_DEFAULT
        return {"enabled": settings["detection_enabled"], "class_id": class_id}

    def set_detection(self, body, actor=None):
        if not isinstance(body, dict) or type(body.get("enabled")) is not bool:
            raise DataClassError(400, "Choose whether to detect personal data")
        if set(body) - {"enabled", "class_id"}:
            raise DataClassError(400, "Send only detection settings")
        with settings_change() as settings:
            self._require_enabled()
            class_id = body.get("class_id", settings.detection_class_id)
            if class_id is None:
                class_id = DETECTION_DEFAULT
            if not isinstance(class_id, str):
                raise DataClassError(400, "Choose a class for detected requests")
            row = DataClass.objects.filter(pk=class_id).first()
            if row is None:
                raise DataClassError(400, "Choose a class for detected requests")
            changes = []
            if settings.detection_enabled != body["enabled"]:
                changes.append(
                    "Turned personal-data detection " + ("on" if body["enabled"] else "off")
                )
            if settings.detection_class_id != row.pk:
                previous = settings.detection_class
                changes.append(
                    "detected requests handled as "
                    + (f"{row.name} instead of {previous.name}" if previous else row.name)
                )
            settings.detection_enabled = body["enabled"]
            settings.detection_class = row
            settings.save(update_fields=["detection_enabled", "detection_class"])
            if actor and changes:
                text = "; ".join(changes)
                self.audit.record_in_transaction(
                    "settings", *actor, text[0].upper() + text[1:]
                )
        return {"enabled": body["enabled"], "class_id": row.pk}

    def list(self, effective_model_ids=None):
        approvals = self._approvals()
        counts = dict(
            ProjectClass.objects.values("data_class_id")
            .annotate(count=Count("project_id"))
            .values_list("data_class_id", "count")
        )
        return [
            {
                "id": identifier,
                "name": name,
                "approved_model_ids": [
                    model_id
                    for model_id, classes in approvals
                    if name in classes
                    and (effective_model_ids is None or model_id in effective_model_ids)
                ],
                "project_count": counts.get(identifier, 0),
            }
            for identifier, name in self._rows()
        ]

    def _set_models(self, old_name, new_name, model_ids):
        for model in ModelApproval.objects.all():
            revised = [item for item in model.approved_classes if item != old_name]
            if model.pk in model_ids:
                revised.append(new_name)
            if revised != model.approved_classes:
                model.approved_classes = revised
                model.save(update_fields=["approved_classes"])

    def add(self, body, effective_model_ids=None, actor=None):
        with settings_change():
            self._require_enabled()
            name = self._validate(
                body.get("name"),
                body.get("approved_model_ids"),
                effective_model_ids=effective_model_ids,
            )
            last = DataClass.objects.aggregate(position=Max("position"))["position"]
            identifier = uuid.uuid4().hex
            DataClass.objects.create(
                id=identifier, name=name, position=0 if last is None else last + 1
            )
            self._set_models(None, name, body["approved_model_ids"])
            if actor:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    f"Added data class {name}; approved models: {', '.join(body['approved_model_ids']) or 'none'}",
                )
        return {
            "id": identifier,
            "name": name,
            "approved_model_ids": body["approved_model_ids"],
            "project_count": 0,
        }

    def edit(self, identifier, body, effective_model_ids=None, actor=None):
        with settings_change():
            self._require_enabled()
            row = DataClass.objects.filter(pk=identifier).first()
            if row is None:
                raise DataClassError(404, "Class not found")
            name = self._validate(
                body.get("name"),
                body.get("approved_model_ids"),
                identifier,
                effective_model_ids,
            )
            previous_models = {
                model_id
                for model_id, classes in self._approvals()
                if row.name in classes
            }
            old_name = row.name
            row.name = name
            row.save(update_fields=["name"])
            self._set_models(old_name, name, body["approved_model_ids"])
            changes = []
            if name != old_name:
                changes.append(f"renamed to {name}")
            if set(body["approved_model_ids"]) != previous_models:
                changes.append(
                    f"approved models: {', '.join(sorted(previous_models)) or 'none'}"
                    f" to {', '.join(sorted(body['approved_model_ids'])) or 'none'}"
                )
            if actor and changes:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    f"Changed data class {old_name}: " + "; ".join(changes),
                )
            count = ProjectClass.objects.filter(data_class_id=identifier).count()
        return {
            "id": identifier,
            "name": name,
            "approved_model_ids": body["approved_model_ids"],
            "project_count": count,
        }

    def remove(self, identifier, actor=None):
        with settings_change():
            self._require_enabled()
            row = DataClass.objects.filter(pk=identifier).first()
            if row is None:
                raise DataClassError(404, "Class not found")
            if ProjectClass.objects.filter(data_class=row).exists():
                raise DataClassError(409, "Projects still use this class")
            if Settings.objects.filter(pk=1, detection_class=row).exists():
                raise DataClassError(
                    409, "Personal-data detection uses this class; choose another first"
                )
            if DataClass.objects.count() == 1:
                raise DataClassError(409, "Keep at least one data class")
            approved_for = [
                model_id
                for model_id, classes in self._approvals()
                if row.name in classes
            ]
            self._set_models(row.name, None, [])
            row.delete()
            if actor:
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    f"Removed data class {row.name}; it was approved for models: "
                    + (", ".join(approved_for) or "none"),
                )
        return {"removed": True}

    def _validate(self, name, model_ids, current_id=None, effective_model_ids=None):
        if not isinstance(name, str):
            raise DataClassError(400, "Enter a class name")
        name = name.strip()
        if not 2 <= len(name) <= 80 or any(ord(character) < 32 for character in name):
            raise DataClassError(400, "Class name must be 2–80 printable characters")
        if any(
            other_name.casefold() == name.casefold() and identifier != current_id
            for identifier, other_name in self._rows()
        ):
            raise DataClassError(409, "A class with this name already exists")
        if (
            not isinstance(model_ids, list)
            or any(not isinstance(item, str) for item in model_ids)
            or len(set(model_ids)) != len(model_ids)
        ):
            raise DataClassError(400, "Choose valid approved models")
        known = {model_id for model_id, _ in self._approvals()}
        if not set(model_ids).issubset(known) or (
            effective_model_ids is not None
            and not set(model_ids).issubset(effective_model_ids)
        ):
            raise DataClassError(400, "Choose models already set up in Keeplane")
        return name
