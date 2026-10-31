"""Which allowed model a developer's task goes to (Spec 004 ST15 and ST17).

Precedence, inside what the project allows (D150):

1. the model the developer switched to,
2. the persona rule for the task's persona,
3. the model for the task's complexity level,
4. the first allowed model, in model ID order.

A step only counts when its model passes the one filter every fallback uses
(``DjangoModelChoice``): set up in Keeplane with its current gateway
definition, allowed for the project's data class, admitted by this mode's
runtime gate including key availability, and authorized for this developer and
project. Otherwise the next step decides, so a persona rule or level never
reaches a model the project may not use or a model only present in the
gateway. The developer's switch is never replaced by a rule or a level: if the
switched-to model is not allowed it is refused, and if only their own key is
unusable the task moves exactly as the model choice already does, in this
order instead of model ID order.

This is advice for the developer's client, not a permit: every gateway request
still passes the entry and selected-model checks. Nothing here judges a task's
complexity; the caller names the level.
"""

import uuid

from accounts.authentication import RuntimeSessionAuthentication, runtime_bearer_only
from common.api import CATALOG
from common.errors import StorageUnavailable
from django.db import DatabaseError
from django.views.decorators.cache import never_cache
from projects.models import Project
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import model_choice
from .authorization import ModelAccessDenied
from .levels import LEVEL_NAMES, level_rows
from .persona_rules import PERSONA_NAMES
from .policy import ModelPolicyUnavailable

DEVELOPER, PERSONA_RULE, LEVEL, FIRST_ALLOWED = (
    "developer",
    "persona_rule",
    "complexity_level",
    "first_allowed",
)
QUERY_FIELDS = {"model_id", "persona", "level"}


class TaskRouting:
    """Apply the precedence above with one ``DjangoModelChoice`` filter."""

    def __init__(self, choice, catalog):
        self.choice, self.catalog = choice, catalog

    def _actor(self, session_token, project_id):
        """The developer and project, checked as model authorization does."""
        authorization = self.choice.authorization
        actor = authorization.identity.session(session_token)
        if actor is None:
            raise ModelAccessDenied(401, "Sign in to Keeplane")
        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            raise ModelAccessDenied(403, "This project is unavailable")
        actor_id, project_id = str(actor["id"]), str(project.pk)
        if authorization.project_access(actor_id, project_id) is not True:
            raise ModelAccessDenied(403, "This project is unavailable")
        return actor_id, project_id

    def _permitted(self, session_token, owner_id, project_id, model_id, eligible):
        if model_id is None or model_id not in eligible:
            return False
        if not self.choice._usable(owner_id, model_id):
            return False
        try:
            # Recheck the developer, project and class for the final choice.
            self.choice.authorization.authorize(session_token, project_id, model_id)
        except ModelAccessDenied as error:
            if error.status == 401:
                raise
            return False
        return True

    def _defaults(self, persona, level, eligible):
        """The persona rule's model, then the level's model, for this project.

        The level's model is worked out from the project's allowed models only:
        an admin's pick wins while it is allowed here, otherwise Keeplane's own
        pick among them.
        """
        steps = []
        if persona is not None:
            steps.append((PERSONA_RULE, self.catalog.persona_rules().get(persona)))
        if level is not None:
            rows = level_rows(
                self.catalog.context_windows(sorted(eligible)),
                self.catalog.level_choices(),
            )
            steps.append(
                (LEVEL, next(row["model_id"] for row in rows if row["level"] == level))
            )
        return steps

    def route(self, session_token, project_id, *, model_id=None, persona=None,
              level=None):
        result = {
            "project_id": project_id,
            "requested_model_id": model_id,
            "persona": persona,
            "level": level,
            "model_id": None,
            "chosen_by": None,
            "reason": None,
        }
        skip = set()
        if model_id is not None:
            chosen = self.choice.choose(session_token, project_id, model_id)
            result["project_id"], result["reason"] = chosen["project_id"], chosen["reason"]
            if chosen["reason"] is None:
                result["model_id"], result["chosen_by"] = model_id, DEVELOPER
                return result
            if chosen["model_id"] is None:
                # Not admitted now for a reason other than the developer's own
                # key: nothing is sent, as the model choice already answers.
                return result
            skip.add(model_id)
        owner_id, project_id = self._actor(session_token, project_id)
        result["project_id"] = project_id
        eligible = self.choice.policy.eligible_model_ids(project_id) - skip
        for chosen_by, candidate in self._defaults(persona, level, eligible):
            if self._permitted(session_token, owner_id, project_id, candidate, eligible):
                result["model_id"], result["chosen_by"] = candidate, chosen_by
                return result
        candidate = self.choice.next_allowed(
            session_token, owner_id, project_id, skip=skip
        )
        if candidate is not None:
            result["model_id"], result["chosen_by"] = candidate, FIRST_ALLOWED
        return result


def route_query(request):
    """The valid query values, or None when the query is malformed."""
    if request.body or not set(request.query_params) <= QUERY_FIELDS:
        return None
    values = {}
    for field in QUERY_FIELDS:
        given = request.query_params.getlist(field)
        if len(given) > 1:
            return None
        values[field] = given[0] if given else None
    model_id = values["model_id"]
    if model_id is not None and (
        not 0 < len(model_id) <= 256
        or any(ord(c) < 32 or ord(c) == 127 for c in model_id)
    ):
        return None
    if values["persona"] is not None and values["persona"] not in PERSONA_NAMES:
        return None
    if values["level"] is not None and values["level"] not in LEVEL_NAMES:
        return None
    return values


def router():
    return TaskRouting(model_choice.chooser(), CATALOG)


@never_cache
@runtime_bearer_only
@api_view(["GET"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def project_task_model(request, project_id):
    """Tell the developer's client which allowed model a task goes to, and why."""
    query = route_query(request)
    if query is None:
        return Response(
            {"error": "Send at most one model ID, persona and level"}, status=400
        )
    try:
        project_id = str(uuid.UUID(project_id))
    except (ValueError, TypeError, AttributeError):
        return Response({"error": "This project is unavailable"}, status=403)
    try:
        result = router().route(request.auth, project_id, **query)
    except ModelAccessDenied as error:
        return Response({"error": error.message}, status=error.status)
    except (ModelPolicyUnavailable, StorageUnavailable, DatabaseError):
        return Response({"error": "Model routing is unavailable"}, status=503)
    return Response(result)
