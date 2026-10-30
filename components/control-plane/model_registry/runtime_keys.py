"""First-party CLI key management; provider dispatch remains disconnected."""

import json
import os
import uuid

from accounts.authentication import RuntimeSessionAuthentication, runtime_bearer_only
from accounts.models import User
from common.api import MODEL_GATEWAY
from common.errors import StorageUnavailable
from django.db import DatabaseError, transaction
from django.views.decorators.cache import never_cache
from projects.access import organization_project_access
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import runtime_views
from .developer_keys import (
    DeveloperKeyError,
    DeveloperKeyRefused,
    DeveloperKeyUnverified,
    DjangoDeveloperKeyStore,
)
from .key_validation import DjangoProviderKeyValidator
from .models import DeveloperProviderKey, ModelApproval, ProviderKeyChoice
from .policy import ModelPolicyUnavailable


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate request field")
        result[key] = value
    return result


def key_store(request, model_id):
    owner_id = request.user.pk

    def reauthenticate(owner):
        live, token = RuntimeSessionAuthentication().authenticate(request)
        if (
            owner is None
            or live.pk != owner_id
            or owner.pk != owner_id
            or token != request.auth
        ):
            raise AuthenticationFailed("Sign in to Keeplane")
        if (
            request.method == "PUT"
            and not ModelApproval.objects.filter(
                pk=model_id, key_choice=ProviderKeyChoice.PERSONAL
            ).exists()
        ):
            raise PermissionDenied("This model does not accept developer keys")

    return DjangoDeveloperKeyStore(
        owner_id,
        os.environ.get("PROVIDER_KEY_DIR", ""),
        validate_key=DjangoProviderKeyValidator(MODEL_GATEWAY),
        reauthenticate=reauthenticate,
    )


@never_cache
@runtime_bearer_only
@api_view(["GET", "PUT", "DELETE"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def provider_keys(request):
    if len(request.body) > 4096:
        return Response({"error": "Request is too large"}, status=413)
    if request.method == "GET":
        if (
            request.body
            or set(request.query_params) != {"model_id"}
            or len(request.query_params.getlist("model_id")) != 1
        ):
            return Response({"error": "Send one model ID"}, status=400)
        body = {"model_id": request.query_params["model_id"]}
    else:
        if request.query_params:
            return Response({"error": "Send fields only in the JSON body"}, status=400)
        if request.content_type.lower() != "application/json":
            return Response({"error": "Send JSON"}, status=415)
        try:
            body = json.loads(request.body, object_pairs_hook=strict_object)
        except (ValueError, UnicodeError, RecursionError):
            return Response({"error": "Send a valid JSON object"}, status=400)
        fields = {"model_id", "key"} if request.method == "PUT" else {"model_id"}
        if not isinstance(body, dict) or set(body) != fields:
            return Response({"error": "Send only the required key fields"}, status=400)
    model_id = body["model_id"]
    if (
        not isinstance(model_id, str)
        or not 0 < len(model_id) <= 256
        or any(ord(c) < 32 or ord(c) == 127 for c in model_id)
    ):
        return Response({"error": "Choose a model"}, status=400)
    if request.method == "PUT":
        key = body["key"]
        if (
            not isinstance(key, str)
            or not 12 <= len(key) <= 512
            or any(not 33 <= ord(c) <= 126 for c in key)
        ):
            return Response({"error": "Enter a valid provider key"}, status=400)
    try:
        store = key_store(request, model_id)
        if request.method == "PUT":
            result = store.put(model_id, key)
        elif request.method == "DELETE":
            result = store.remove(model_id)
        else:
            result = store.status(model_id, registration_only=True)
    except DeveloperKeyRefused:
        return Response({"error": "The provider refused the key"}, status=400)
    except (DeveloperKeyUnverified, StorageUnavailable, ValueError, OSError):
        return Response(
            {"error": "The provider key could not be verified or saved"}, status=503
        )
    except DeveloperKeyError:
        return Response(
            {"error": "The provider key request could not be completed"}, status=400
        )
    return Response(result)


@never_cache
@runtime_bearer_only
@api_view(["GET"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def project_provider_keys(request, project_id):
    """List allowed models and saved registrations, never provider health."""
    if request.body or request.query_params:
        return Response({"error": "Send an empty key-list request"}, status=400)
    try:
        project_id = str(uuid.UUID(project_id))
    except (ValueError, TypeError, AttributeError):
        raise PermissionDenied("This project is unavailable") from None
    try:
        with transaction.atomic():
            User.objects.select_for_update().filter(pk=request.user.pk).first()
            owner, token = RuntimeSessionAuthentication().authenticate(request)
            if owner.pk != request.user.pk or token != request.auth:
                raise AuthenticationFailed("Sign in to Keeplane")
            if not organization_project_access(str(owner.pk), project_id):
                raise PermissionDenied("This project is unavailable")
            allowed = runtime_views.model_policy().eligible_model_ids(project_id)
            choices = dict(
                ModelApproval.objects.filter(pk__in=allowed).values_list(
                    "pk", "key_choice"
                )
            )
            if set(choices) != allowed or any(
                choice not in ProviderKeyChoice.values for choice in choices.values()
            ):
                raise ModelPolicyUnavailable()
            added = set(
                DeveloperProviderKey.objects.filter(owner=owner, model_id__in=allowed)
                .exclude(key_name="")
                .values_list("model_id", flat=True)
            )
            rows = [
                {
                    "id": name,
                    "own_key_required": choices[name] == ProviderKeyChoice.PERSONAL,
                    "status": ("added" if name in added else "missing")
                    if choices[name] == ProviderKeyChoice.PERSONAL
                    else None,
                }
                for name in sorted(allowed)
            ]
    except (DatabaseError, StorageUnavailable, ModelPolicyUnavailable):
        return Response({"error": "Key registration list is unavailable"}, status=503)
    return Response({"project_id": project_id, "models": rows})
