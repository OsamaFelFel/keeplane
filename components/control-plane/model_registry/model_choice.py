"""Choose another allowed model when a developer's own key is not usable.

The choice reads key registration metadata and, through the runtime gate, the
digest of a shared key file only: it never reads a developer's own key, and
never sends or changes any key. It is advice for the developer's client, not a permit:
every gateway request still passes the entry and selected-model checks.
"""

import os
import uuid

from accounts.authentication import RuntimeSessionAuthentication, runtime_bearer_only
from accounts.cli_credentials import RuntimeIdentity
from common.api import IDENTITY, MODEL_GATEWAY
from common.errors import StorageUnavailable
from common.storage import storage_service
from django.conf import settings
from django.db import DatabaseError
from django.views.decorators.cache import never_cache
from projects.access import organization_project_access
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import runtime_views
from .authorization import DjangoModelAuthorization, ModelAccessDenied
from .installed_runtime import DjangoInstalledRuntimeGate
from .models import DeveloperProviderKey, ModelApproval, ProviderKeyChoice
from .policy import ModelPolicyUnavailable
from .provider_keys import DjangoSharedKeyAvailability


def key_problem(owner_id, model_id, definition_fingerprint):
    """Why an owner's key cannot be used, matching the key resolver's rule.

    The resolver uses only a registration bound to the current definition and
    not confirmed as refused; anything else is reported as a missing key.
    """
    row = (
        DeveloperProviderKey.objects.filter(owner_id=owner_id, model_id=model_id)
        .values("key_name", "refused", "validation_fingerprint")
        .first()
    )
    if row is None or not row["key_name"]:
        return "missing"
    if row["refused"]:
        return "refused"
    if not definition_fingerprint or row["validation_fingerprint"] != definition_fingerprint:
        return "outdated"
    return None


@storage_service
class DjangoModelChoice:
    """Keep the requested model unless its owner key is not usable.

    Another model is chosen only from the project's currently eligible models,
    in model ID order, and only when the same runtime gate that admits a task
    (installation, setup, shared or owner key, project class) accepts it.
    A requested model that gate refuses for any other reason is reported as
    ``unavailable`` with no model, so the client sends nothing.
    """

    def __init__(self, identity, policy, gateway, directory, *, project_access,
                 managed, manifest_file):
        self.authorization = DjangoModelAuthorization(
            identity, policy, project_access=project_access
        )
        self.policy, self.gateway, self.directory = policy, gateway, directory
        self.managed, self.manifest_file = managed, manifest_file

    def _usable(self, owner_id, model_id):
        """Return True only if the current runtime gate would admit this model."""
        try:
            if self.managed:
                enrollment = DjangoInstalledRuntimeGate(
                    self.gateway, self.manifest_file, self.directory
                ).require_installed(model_id)
                if enrollment["key_choice"] == ProviderKeyChoice.PERSONAL:
                    return key_problem(owner_id, model_id, enrollment["fingerprint"]) is None
                return True
            DjangoSharedKeyAvailability(self.gateway, self.directory).require_available(
                model_id
            )
            return True
        except (ModelAccessDenied, ModelPolicyUnavailable):
            return False

    def choose(self, session_token, project_id, model_id):
        decision = self.authorization.authorize(session_token, project_id, model_id)
        owner_id, project_id = decision["actor_id"], decision["project_id"]
        approval = (
            ModelApproval.objects.filter(pk=model_id)
            .values("key_choice", "gateway_fingerprint")
            .first()
        )
        if approval is None:
            raise ModelPolicyUnavailable("Model setup is unavailable")
        reason = None
        if approval["key_choice"] == ProviderKeyChoice.PERSONAL:
            reason = key_problem(owner_id, model_id, approval["gateway_fingerprint"])
        result = {
            "project_id": project_id,
            "requested_model_id": model_id,
            "model_id": model_id,
            "reason": reason,
        }
        if reason is None:
            if not self._usable(owner_id, model_id):
                # Spec 005 ST19: an approved model that the runtime gate would
                # not admit now (not installed, setup changed or shared key
                # gone) gets no task. Nothing moves to another model here:
                # moving a task off a model that is down is still open (ST16).
                result["model_id"], result["reason"] = None, "unavailable"
            return result
        result["model_id"] = self.next_allowed(
            session_token, owner_id, project_id, skip={model_id}
        )
        return result

    def next_allowed(self, session_token, owner_id, project_id, *, skip):
        """The one filter every fallback uses: the first permitted model, or None.

        A candidate must be registered and set up in Keeplane with its current
        definition (so a model only present in the gateway never qualifies),
        allowed for the project's class, and pass this mode's runtime gate,
        including shared or the developer's own key availability. The order is
        model ID until complexity routing (task 004-03) sets a preference.
        """
        for candidate in sorted(self.policy.eligible_model_ids(project_id) - set(skip)):
            if self._usable(owner_id, candidate):
                try:
                    # Recheck the developer, project and class for the final choice.
                    self.authorization.authorize(session_token, project_id, candidate)
                except ModelAccessDenied as error:
                    if error.status == 401:
                        raise
                    continue
                return candidate
        return None

    def alternatives(self, session_token, project_id, model_id):
        """Every other model the developer could switch to, in model ID order.

        Used when the requested model is down or too small for the task (Spec
        004 ST16): Keeplane never moves such a task itself, it only tells the
        developer. Each candidate comes from ``next_allowed``, the one filter
        every fallback uses, so gateway-only models never appear.
        """
        decision = self.authorization.authorize(session_token, project_id, model_id)
        owner_id, project_id = decision["actor_id"], decision["project_id"]
        tried, found = {model_id}, []
        while len(found) < MAX_ALTERNATIVES:
            candidate = self.next_allowed(session_token, owner_id, project_id, skip=tried)
            if candidate is None:
                break
            tried.add(candidate)
            found.append(candidate)
        return {"project_id": project_id, "model_id": model_id, "alternatives": found}


MAX_ALTERNATIVES = 32


def one_model_id(request):
    """Return the single valid ``model_id`` query value, or None."""
    if (
        request.body
        or set(request.query_params) != {"model_id"}
        or len(request.query_params.getlist("model_id")) != 1
    ):
        return None
    model_id = request.query_params["model_id"]
    if (
        not 0 < len(model_id) <= 256
        or any(ord(c) < 32 or ord(c) == 127 for c in model_id)
    ):
        return None
    return model_id


def chooser():
    return DjangoModelChoice(
        RuntimeIdentity(IDENTITY),
        runtime_views.model_policy(),
        MODEL_GATEWAY,
        os.environ.get("PROVIDER_KEY_DIR", ""),
        project_access=organization_project_access,
        managed=os.environ.get("GATEWAY_MODE", "managed") == "managed",
        manifest_file=settings.RUNTIME_GUARD_MANIFEST_FILE,
    )


@never_cache
@runtime_bearer_only
@api_view(["GET"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def project_model_alternatives(request, project_id):
    """List the allowed models a developer can switch to; nothing is moved."""
    model_id = one_model_id(request)
    if model_id is None:
        return Response({"error": "Send one model ID"}, status=400)
    try:
        project_id = str(uuid.UUID(project_id))
    except (ValueError, TypeError, AttributeError):
        return Response({"error": "This project is unavailable"}, status=403)
    try:
        result = chooser().alternatives(request.auth, project_id, model_id)
    except ModelAccessDenied as error:
        return Response({"error": error.message}, status=error.status)
    except (ModelPolicyUnavailable, StorageUnavailable, DatabaseError):
        return Response({"error": "Model alternatives are unavailable"}, status=503)
    return Response(result)


@never_cache
@runtime_bearer_only
@api_view(["GET"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def project_model_choice(request, project_id):
    """Tell the CLI which allowed model a task should use, and why it changed."""
    model_id = one_model_id(request)
    if model_id is None:
        return Response({"error": "Send one model ID"}, status=400)
    try:
        project_id = str(uuid.UUID(project_id))
    except (ValueError, TypeError, AttributeError):
        return Response({"error": "This project is unavailable"}, status=403)
    try:
        result = chooser().choose(request.auth, project_id, model_id)
    except ModelAccessDenied as error:
        return Response({"error": error.message}, status=error.status)
    except (ModelPolicyUnavailable, StorageUnavailable, DatabaseError):
        return Response({"error": "Model choice is unavailable"}, status=503)
    return Response(result)
