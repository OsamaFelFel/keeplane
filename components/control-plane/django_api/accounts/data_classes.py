"""Data-class storage port with PostgreSQL transaction boundaries."""

import uuid
from django.db.models import Count, Max

from data_classes import DataClassError, DataClassStore, STARTERS
from .models import DataClass, ModelApproval, ProjectClass, Settings
from .storage import settings_change, storage_service


@storage_service
class DjangoDataClassStore(DataClassStore):
    def __init__(self, audit):
        self.audit = audit

    def _rows(self, connection):
        return list(DataClass.objects.order_by("position", "name").values_list("id", "name"))

    def _approvals(self, connection):
        return list(ModelApproval.objects.order_by("model_id").values_list("model_id", "approved_classes"))

    def enabled(self):
        return Settings.objects.filter(pk=1, classes_enabled=True).exists()

    def _require_enabled(self, connection):
        if not self.enabled():
            raise DataClassError(409, "Turn on data classes first")

    def set_enabled(self, enabled, actor=None):
        if type(enabled) is not bool:
            raise DataClassError(400, "Choose whether to use data classes")
        with settings_change() as settings:
            if enabled and not DataClass.objects.exists():
                DataClass.objects.bulk_create([DataClass(id=identifier, name=name, position=position)
                                               for position, (identifier, name) in enumerate(STARTERS)])
            if settings.classes_enabled != enabled:
                settings.classes_enabled = enabled
                settings.save(update_fields=["classes_enabled"])
                if actor:
                    self.audit.record_in_transaction(None, "settings", *actor,
                                                      "Turned data classes " + ("on" if enabled else "off"))
        return {"enabled": enabled}

    def list(self, effective_model_ids=None):
        approvals = self._approvals(None)
        counts = dict(ProjectClass.objects.values("data_class_id").annotate(count=Count("project_id")).values_list("data_class_id", "count"))
        return [{"id": identifier, "name": name,
                 "approved_model_ids": [model_id for model_id, classes in approvals if name in classes
                                        and (effective_model_ids is None or model_id in effective_model_ids)],
                 "project_count": counts.get(identifier, 0)} for identifier, name in self._rows(None)]

    def _set_models(self, connection, old_name, new_name, model_ids):
        for model in ModelApproval.objects.all():
            revised = [item for item in model.approved_classes if item != old_name]
            if model.pk in model_ids:
                revised.append(new_name)
            if revised != model.approved_classes:
                model.approved_classes = revised
                model.save(update_fields=["approved_classes"])

    def add(self, body, effective_model_ids=None, actor=None):
        with settings_change():
            self._require_enabled(None)
            name = self._validate(None, body.get("name"), body.get("approved_model_ids"), effective_model_ids=effective_model_ids)
            last = DataClass.objects.aggregate(position=Max("position"))["position"]
            identifier = uuid.uuid4().hex
            DataClass.objects.create(id=identifier, name=name, position=0 if last is None else last + 1)
            self._set_models(None, None, name, body["approved_model_ids"])
            if actor:
                self.audit.record_in_transaction(None, "settings", *actor,
                    f"Added data class {name}; approved models: {', '.join(body['approved_model_ids']) or 'none'}")
        return {"id": identifier, "name": name, "approved_model_ids": body["approved_model_ids"], "project_count": 0}

    def edit(self, identifier, body, effective_model_ids=None, actor=None):
        with settings_change():
            self._require_enabled(None)
            row = DataClass.objects.filter(pk=identifier).first()
            if row is None:
                raise DataClassError(404, "Class not found")
            name = self._validate(None, body.get("name"), body.get("approved_model_ids"), identifier, effective_model_ids)
            previous_models = {model_id for model_id, classes in self._approvals(None) if row.name in classes}
            old_name = row.name
            row.name = name
            row.save(update_fields=["name"])
            self._set_models(None, old_name, name, body["approved_model_ids"])
            if actor and (name != old_name or set(body["approved_model_ids"]) != previous_models):
                self.audit.record_in_transaction(None, "settings", *actor,
                    f"Changed data class {old_name} to {name}; approved models: {', '.join(body['approved_model_ids']) or 'none'}")
            count = ProjectClass.objects.filter(data_class_id=identifier).count()
        return {"id": identifier, "name": name, "approved_model_ids": body["approved_model_ids"], "project_count": count}

    def remove(self, identifier, actor=None):
        with settings_change():
            self._require_enabled(None)
            row = DataClass.objects.filter(pk=identifier).first()
            if row is None:
                raise DataClassError(404, "Class not found")
            if ProjectClass.objects.filter(data_class=row).exists():
                raise DataClassError(409, "Projects still use this class")
            if DataClass.objects.count() == 1:
                raise DataClassError(409, "Keep at least one data class")
            self._set_models(None, row.name, None, [])
            row.delete()
            if actor:
                self.audit.record_in_transaction(None, "settings", *actor, f"Removed data class {row.name}")
        return {"removed": True}
