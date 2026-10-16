"""Current model eligibility for an already authorized project context.

This is an internal policy query, not authentication or a gateway dispatch gate.
"""

from common.storage import storage_service
from data_classes.models import DataClass, ProjectClass, Settings
from django.db import connection, transaction

from .fingerprints import fingerprint
from .models import ModelApproval, ProviderKeyChoice


class ModelPolicyUnavailable(Exception):
    """No eligibility decision can safely be made from the available policy."""


def registry_rows(body, field):
    rows = body.get(field) if isinstance(body, dict) else None
    if not isinstance(rows, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("id"), str)
        or not 0 < len(row["id"]) <= 256
        for row in rows
    ):
        raise ModelPolicyUnavailable("The gateway registry could not be verified")
    if len({row["id"] for row in rows}) != len(rows):
        raise ModelPolicyUnavailable("The gateway registry is ambiguous")
    return rows


@storage_service
class DjangoModelPolicy:
    def __init__(self, gateway, file_config=None):
        self.gateway, self.file_config = gateway, file_config

    def eligible_model_ids(self, project_id):
        """Read policy on each call; never accept a client-provided data class.

        The caller must authenticate the developer and authorize project access
        first. All policy writers must lock Settings, as settings_change does.
        Provider-key availability and final dispatch require separate checks.
        """
        if not isinstance(project_id, str) or not 0 < len(project_id) <= 64:
            raise ValueError("Choose a project context")
        status, listing = self.gateway.models()
        if status != 200:
            raise ModelPolicyUnavailable("The gateway model list is unavailable")
        status, registry = self.gateway.resources()
        if status != 200:
            raise ModelPolicyUnavailable("The gateway definitions are unavailable")
        model_ids = {row["id"] for row in registry_rows(listing, "data")}
        resources = registry_rows(registry, "resources")
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_is_in_recovery()")
                    if cursor.fetchone() != (False,):
                        raise ModelPolicyUnavailable(
                            "Policy requires the primary database"
                        )
            # Match the existing class/approval writer lock, without creating
            # missing policy or caching an earlier decision across requests.
            settings = Settings.objects.select_for_update().filter(pk=1).first()
            if settings is None:
                raise ModelPolicyUnavailable("Data-class settings are missing")
            class_name = None
            if settings.classes_enabled:
                class_id = (
                    ProjectClass.objects.filter(pk=project_id)
                    .values_list("data_class_id", flat=True)
                    .first()
                )
                if class_id is not None:
                    class_name = (
                        DataClass.objects.filter(pk=class_id)
                        .values_list("name", flat=True)
                        .first()
                    )
                    if class_name is None:
                        raise ModelPolicyUnavailable("The project class is missing")
            eligible = set()
            for approval in ModelApproval.objects.filter(pk__in=model_ids):
                classes = approval.approved_classes
                if (
                    not isinstance(classes, list)
                    or any(not isinstance(name, str) for name in classes)
                    or len(set(classes)) != len(classes)
                    or approval.key_choice not in ProviderKeyChoice.values
                ):
                    raise ModelPolicyUnavailable("Model setup is incomplete")
                current = fingerprint(approval.pk, resources, self.file_config)
                if current and current == approval.gateway_fingerprint:
                    if class_name is None or class_name in classes:
                        eligible.add(approval.pk)
            return frozenset(eligible)
