"""Private metadata-only policy decisions for a gateway integration."""

import hmac
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

from accounts.authentication import RuntimeSessionAuthentication, runtime_bearer_only
from accounts.cli_credentials import RuntimeIdentity
from common.api import IDENTITY, MODEL_GATEWAY
from common.errors import StorageUnavailable
from django.conf import settings
from django.views.decorators.cache import never_cache
from projects.access import organization_project_access
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .authorization import DjangoModelAuthorization, ModelAccessDenied
from .installed_runtime import DjangoInstalledRuntimeGate, unique_pairs
from .policy import ModelPolicyUnavailable
from .provider_keys import DjangoSharedKeyAvailability
from .runtime_views import model_policy


def private_key(filename):
    """Read current private credentials; no client may select the file."""
    path = Path(filename)
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


def gateway_key():
    return private_key(settings.RUNTIME_AUTHORIZER_KEY_FILE)


class OperatorValidationUnavailable(APIException):
    status_code = 503

    def __init__(self):
        super().__init__({"error": "Operator validation is unavailable"})


class OperatorValidationAuthentication(BaseAuthentication):
    """Both current private credentials, never a browser cookie or user Bearer."""

    def authenticate(self, request):
        supplied = re.fullmatch(
            r"Bearer ([A-Za-z0-9_-]{32,256})",
            request.headers.get("Authorization", ""),
            flags=re.IGNORECASE,
        )
        callback = request.headers.get("X-Keeplane-Gateway-Credential", "")
        try:
            expected = private_key(os.environ.get("GATEWAY_RUNTIME_KEY_FILE", ""))
            expected_callback = gateway_key()
        except ModelPolicyUnavailable:
            raise OperatorValidationUnavailable() from None
        if (
            os.environ.get("GATEWAY_MODE", "managed") != "managed"
            or request.headers.get("X-Keeplane-Installed-Runtime") != "operator"
            or supplied is None
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", callback)
            or not hmac.compare_digest(supplied[1].encode("ascii"), expected)
            or not hmac.compare_digest(callback.encode("ascii"), expected_callback)
        ):
            raise AuthenticationFailed({"error": "Operator validation is unavailable"})
        return SimpleNamespace(is_authenticated=True), None


def callback_metadata(request, *, selected=False, with_project=True):
    expected = gateway_key()
    supplied = request.headers.get("X-Keeplane-Gateway-Credential", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", supplied) or not hmac.compare_digest(
        supplied.encode("ascii"), expected
    ):
        return Response({"error": "Gateway credential is invalid"}, status=403)
    if request.content_type != "application/json":
        return Response({"error": "Send JSON metadata"}, status=415)
    raw = request.read(4097)
    if len(raw) > 4096:
        return Response({"error": "Authorization metadata is too large"}, status=413)
    try:
        body = json.loads(raw, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return Response({"error": "Send valid JSON metadata"}, status=400)
    fields = {"model_id"}
    if with_project:
        fields.add("project_id")
    if selected:
        fields.add("definition_fingerprint")
    if (
        not isinstance(body, dict)
        or set(body) != fields
        or (
            with_project
            and (
                not isinstance(body["project_id"], str)
                or not 0 < len(body["project_id"]) <= 64
            )
        )
        or not isinstance(body["model_id"], str)
        or not 0 < len(body["model_id"]) <= 256
        or (
            selected
            and (
                not isinstance(body["definition_fingerprint"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", body["definition_fingerprint"])
            )
        )
    ):
        message = (
            "Send only a project ID and model ID"
            if with_project
            else "Send only model validation metadata"
        )
        return Response({"error": message}, status=400)
    return body


def authorized_model(request, body):
    return DjangoModelAuthorization(
        RuntimeIdentity(IDENTITY),
        model_policy(),
        project_access=organization_project_access,
    ).authorize(request.auth, body["project_id"], body["model_id"])


@never_cache
@runtime_bearer_only
@api_view(["POST"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def authorize(request):
    try:
        body = callback_metadata(request)
        if isinstance(body, Response):
            return body
        result = authorized_model(request, body)
        DjangoSharedKeyAvailability(
            MODEL_GATEWAY, os.environ.get("PROVIDER_KEY_DIR", "")
        ).require_available(result["model_id"])
    except ModelAccessDenied as error:
        return Response({"error": error.message}, status=error.status)
    except (ModelPolicyUnavailable, StorageUnavailable):
        return Response({"error": "Gateway authorization is unavailable"}, status=503)
    return Response(result)


@never_cache
@runtime_bearer_only
@api_view(["POST"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def authorize_installed(request, *, selected=False):
    """Fixed operator enrollment only; this does not install a public listener."""
    try:
        body = callback_metadata(request, selected=selected)
        if isinstance(body, Response):
            return body
        if os.environ.get("GATEWAY_MODE", "managed") != "managed":
            raise ModelPolicyUnavailable("Managed runtime installation is required")
        DjangoInstalledRuntimeGate(
            MODEL_GATEWAY,
            settings.RUNTIME_GUARD_MANIFEST_FILE,
            os.environ.get("PROVIDER_KEY_DIR", ""),
        ).require_installed(body["model_id"], body.get("definition_fingerprint"))
        result = authorized_model(request, body)
    except ModelAccessDenied as error:
        return Response({"error": error.message}, status=error.status)
    except (ModelPolicyUnavailable, StorageUnavailable):
        return Response({"error": "Gateway authorization is unavailable"}, status=503)
    return Response(result)


@never_cache
@runtime_bearer_only
@api_view(["POST"])
@authentication_classes([OperatorValidationAuthentication])
@permission_classes([IsAuthenticated])
def authorize_operator_validation(request):
    """Preserve private raw-listener validation; never authorize developer work."""
    try:
        body = callback_metadata(request, selected=True, with_project=False)
        if isinstance(body, Response):
            return body
    except ModelPolicyUnavailable:
        return Response({"error": "Operator validation is unavailable"}, status=503)
    # This privileged callback deliberately does not attest approval, enrollment or
    # user access: model setup validates before approval and while enrollment is off.
    return Response({"allowed": True})
