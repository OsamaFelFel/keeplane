"""Compose current identity, project access and model eligibility internally."""

import uuid

from common.storage import storage_service
from projects.models import Project
from .policy import ModelPolicyUnavailable


class ModelAccessDenied(Exception):
    def __init__(self, status, message, *, held=None):
        super().__init__(message)
        self.status, self.message = status, message
        # A request held to the detection class and refused for this model:
        # the server's actor, project, model and class, never request text.
        self.held = held


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

    def authorize(self, session_token, project_id, model_id, *, personal_data=None):
        """Resolve fresh server state; return no credential or client policy claim.

        ``personal_data`` is the detector's verdict for a gateway request
        check (Spec 005 ST20); advice paths leave it None. When the request is
        held, the result also names the detection class as ``held_class``.
        """
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
        if personal_data is None:
            eligible, held_class = self.model_policy.eligible_model_ids(project_id), None
        else:
            eligible, held_class = self.model_policy.eligibility(
                project_id, personal_data
            )
        if model_id not in eligible:
            if held_class is not None:
                raise ModelAccessDenied(
                    403,
                    f"This request is handled as {held_class} and {model_id} "
                    "isn't approved for it, so nothing was sent. Run it with a "
                    f"model approved for {held_class}, or ask your admin to "
                    "approve one.",
                    held={
                        "actor_id": actor_id,
                        "project_id": project_id,
                        "model_id": model_id,
                        "held_class": held_class,
                        "allowed": False,
                    },
                )
            raise ModelAccessDenied(403, "This model is not eligible for the project")
        result = {"actor_id": actor_id, "project_id": project_id, "model_id": model_id}
        if held_class is not None:
            result["held_class"] = held_class
        return result
