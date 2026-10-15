"""Record authenticated project use without changing onboarding or class policy."""

import uuid

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from common.storage import storage_service
from .models import Project, ProjectUse


class ProjectError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


@storage_service
class DjangoProjectStore:
    def register_use(self, user_id, project_id, name):
        """Caller supplies the authenticated account, never a client user claim.

        The opaque project ID is requested context, not proof of content origin.
        This records use only; it grants no model access or class assignment.
        """
        try:
            user_id = uuid.UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            raise ProjectError(401, "Sign in to Keeplane")
        try:
            project_id = uuid.UUID(str(project_id))
        except (ValueError, TypeError, AttributeError):
            raise ProjectError(400, "Use a valid project ID")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ProjectError(400, "Enter a project name up to 120 characters")
        name = name.strip()
        if not name.isprintable():
            raise ProjectError(400, "Enter a project name without control characters")

        with transaction.atomic():
            if not User.objects.select_for_update().filter(
                pk=user_id, is_active=True
            ).exists():
                raise ProjectError(401, "Sign in to Keeplane")
            now = timezone.now()
            project, _ = Project.objects.get_or_create(
                pk=project_id,
                defaults={"name": name, "first_seen_at": now, "last_seen_at": now},
            )
            project = Project.objects.select_for_update().get(pk=project.pk)
            # Another account may have used this project while we waited.
            now = timezone.now()
            ProjectUse.objects.update_or_create(
                project=project,
                user_id=user_id,
                defaults={"last_seen_at": now},
                create_defaults={"first_seen_at": now, "last_seen_at": now},
            )
            project.last_seen_at = now
            project.save(update_fields=["last_seen_at"])
            return {"id": str(project.pk), "name": project.name}
