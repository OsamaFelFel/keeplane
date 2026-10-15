"""Assign current server-owned project classes and Audit them atomically."""

import uuid

from common.storage import settings_change, storage_service
from data_classes.models import DataClass, ProjectClass

from .models import Project
from .services import ProjectError


@storage_service
class DjangoProjectClasses:
    def __init__(self, audit):
        self.audit = audit

    def assign(self, project_id, class_id, actor):
        try:
            project_id = uuid.UUID(str(project_id))
        except (ValueError, TypeError, AttributeError):
            raise ProjectError(400, "Use a valid project ID")
        if class_id is not None and (
            not isinstance(class_id, str) or len(class_id) > 64
        ):
            raise ProjectError(400, "Choose a data class or none")
        with settings_change() as settings:
            if not settings.classes_enabled:
                raise ProjectError(409, "Turn on data classes first")
            project = Project.objects.filter(pk=project_id).first()
            if project is None:
                raise ProjectError(404, "Project not found")
            chosen = (
                DataClass.objects.filter(pk=class_id).first()
                if class_id is not None
                else None
            )
            if class_id is not None and chosen is None:
                raise ProjectError(400, "Choose an existing data class")
            previous = (
                ProjectClass.objects.filter(project_id=str(project.pk))
                .select_related("data_class")
                .first()
            )
            previous_id = previous.data_class_id if previous else None
            if previous_id != class_id:
                if chosen:
                    ProjectClass.objects.update_or_create(
                        project_id=str(project.pk), defaults={"data_class": chosen}
                    )
                else:
                    ProjectClass.objects.filter(project_id=str(project.pk)).delete()
                self.audit.record_in_transaction(
                    "settings",
                    *actor,
                    f"Changed data class for project {project.name} ({project.pk}) "
                    f"from {previous.data_class.name if previous else 'none'} "
                    f"to {chosen.name if chosen else 'none'}",
                )
            return {
                "id": str(project.pk),
                "name": project.name,
                "data_class": {"id": chosen.pk, "name": chosen.name}
                if chosen
                else None,
            }
