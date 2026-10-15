"""Private metadata-only policy decisions for a gateway integration."""

import hmac
import json
import os
import re
from pathlib import Path

from accounts.authentication import RuntimeSessionAuthentication, runtime_bearer_only
from common.api import IDENTITY, MODEL_GATEWAY
from common.errors import StorageUnavailable
from django.conf import settings
from django.views.decorators.cache import never_cache
from projects.access import organization_project_access
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .authorization import DjangoModelAuthorization, ModelAccessDenied
from .policy import ModelPolicyUnavailable
from .provider_keys import DjangoSharedKeyAvailability
from .runtime_views import model_policy


def gateway_key():
    """Read on each decision so replacing the operator secret withdraws the old key."""
    path = Path(settings.RUNTIME_AUTHORIZER_KEY_FILE)
    if not path.is_absolute():
        raise ModelPolicyUnavailable("Gateway authorization is unavailable")
    try:
        with path.open("rb") as source:
            raw = source.read(259)
    except OSError:
        raise ModelPolicyUnavailable("Gateway authorization is unavailable")
    key = raw.strip()
    if len(raw) > 258 or not re.fullmatch(rb"[A-Za-z0-9_-]{32,256}", key):
        raise ModelPolicyUnavailable("Gateway authorization is unavailable")
    return key


@never_cache
@runtime_bearer_only
@api_view(["POST"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def authorize(request):
    try:
        expected = gateway_key()
        supplied = request.headers.get("X-Keeplane-Gateway-Credential", "")
        if not re.fullmatch(
            r"[A-Za-z0-9_-]{32,256}", supplied
        ) or not hmac.compare_digest(supplied.encode("ascii"), expected):
            return Response({"error": "Gateway credential is invalid"}, status=403)
        if request.content_type != "application/json":
            return Response({"error": "Send JSON metadata"}, status=415)
        raw = request.read(4097)
        if len(raw) > 4096:
            return Response(
                {"error": "Authorization metadata is too large"}, status=413
            )
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return Response({"error": "Send valid JSON metadata"}, status=400)
        if (
            not isinstance(body, dict)
            or set(body) != {"project_id", "model_id"}
            or not isinstance(body["project_id"], str)
            or not 0 < len(body["project_id"]) <= 64
            or not isinstance(body["model_id"], str)
            or not 0 < len(body["model_id"]) <= 256
        ):
            return Response(
                {"error": "Send only a project ID and model ID"}, status=400
            )
        result = DjangoModelAuthorization(
            IDENTITY, model_policy(), project_access=organization_project_access
        ).authorize(request.auth, body["project_id"], body["model_id"])
        DjangoSharedKeyAvailability(
            MODEL_GATEWAY, os.environ.get("PROVIDER_KEY_DIR", "")
        ).require_available(result["model_id"])
    except ModelAccessDenied as error:
        return Response({"error": error.message}, status=error.status)
    except (ModelPolicyUnavailable, StorageUnavailable):
        return Response({"error": "Gateway authorization is unavailable"}, status=503)
    return Response(result)
