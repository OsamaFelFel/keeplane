"""Compose current identity, project access and model eligibility internally."""

import uuid

from common.storage import storage_service
from projects.models import Project
from .policy import ModelPolicyUnavailable


class ModelAccessDenied(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


@storage_service
class DjangoModelAuthorization:
    def __init__(self, identity, model_policy, *, project_access):
        """project_access(actor_id, project_id) is a required server policy.

        It must return literal True to allow access; usage is not an access grant.
        No project membership rule is implied by this internal service.
        """
        if not callable(project_access):
            raise ModelPolicyUnavailable("Configure a server project-access policy")
        self.identity, self.model_policy = identity, model_policy
        self.project_access = project_access

    def authorize(self, session_token, project_id, model_id):
        """Resolve fresh server state; return no credential or client policy claim."""
        actor = self.identity.session(session_token)
        if actor is None:
            raise ModelAccessDenied(401, "Sign in to Keeplane")
        try:
            project_id = uuid.UUID(str(project_id))
        except (ValueError, TypeError, AttributeError):
            raise ModelAccessDenied(403, "This project is unavailable")
        if not isinstance(model_id, str) or not 0 < len(model_id) <= 256:
            raise ModelAccessDenied(400, "Choose a model")
        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            raise ModelAccessDenied(403, "This project is unavailable")
        actor_id, project_id = str(actor["id"]), str(project.pk)
        if self.project_access(actor_id, project_id) is not True:
            raise ModelAccessDenied(403, "This project is unavailable")
        if model_id not in self.model_policy.eligible_model_ids(project_id):
            raise ModelAccessDenied(403, "This model is not eligible for the project")
        return {"actor_id": actor_id, "project_id": project_id, "model_id": model_id}
