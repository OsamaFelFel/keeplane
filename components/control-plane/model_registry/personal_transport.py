"""Private provider-key handoff; not an issuer or a runtime enrollment."""

import hmac
import os
import re
from types import SimpleNamespace
from urllib.parse import parse_qs

from accounts.authentication import runtime_bearer_only
from accounts.cli_credentials import RuntimeIdentity
from common.api import IDENTITY, MODEL_GATEWAY, MODEL_GATEWAY_COPIES
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

from .authorization import ModelAccessDenied
from .guard_status import installed_gate, per_copy_check, valid_copy_name
from .personal_dispatch import DjangoPersonalDispatch
from .policy import ModelPolicyUnavailable
from .runtime_callback import gateway_key
from .runtime_views import model_policy

ACCESS_TYPE = "urn:ietf:params:oauth:token-type:access_token"
EXCHANGE_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"


class GatewayTransportUnavailable(APIException):
    status_code = 503
    default_detail = "Private provider transport is unavailable"


class GatewayTransportAuthentication(BaseAuthentication):
    """Only the current operator callback secret authenticates this adapter."""

    def authenticate(self, request):
        try:
            expected = gateway_key()
        except ModelPolicyUnavailable:
            raise GatewayTransportUnavailable() from None
        supplied = request.headers.get("X-Keeplane-Gateway-Credential", "")
        if not re.fullmatch(
            r"[A-Za-z0-9_-]{32,256}", supplied
        ) or not hmac.compare_digest(supplied.encode("ascii"), expected):
            raise AuthenticationFailed("Private gateway credential is required")
        return SimpleNamespace(is_authenticated=True), None

    def authenticate_header(self, request):
        return "Keeplane-Gateway"


def metadata(request, *, copy=False):
    """The exchange's fields; ``copy`` requires the sending gateway copy's name."""
    if request.content_type != "application/x-www-form-urlencoded":
        raise ValueError()
    raw = request.read(4097)
    if len(raw) > 4096:
        raise ValueError()
    fields = parse_qs(
        raw.decode("ascii"),
        keep_blank_values=True,
        strict_parsing=True,
        encoding="utf-8",
        errors="strict",
        max_num_fields=8 if copy else 7,
    )
    required = {
        "grant_type",
        "subject_token_type",
        "subject_token",
        "project_id",
        "model_id",
        "definition_fingerprint",
    }
    if copy:
        required.add("gateway_copy")
    if set(fields) not in (required, required | {"requested_token_type"}) or any(
        len(value) != 1 for value in fields.values()
    ):
        raise ValueError()
    body = {name: value[0] for name, value in fields.items()}
    if (
        body["grant_type"] != EXCHANGE_TYPE
        or body["subject_token_type"] != ACCESS_TYPE
        or body.get("requested_token_type", ACCESS_TYPE) != ACCESS_TYPE
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", body["subject_token"])
        or not 0 < len(body["project_id"]) <= 64
        or not 0 < len(body["model_id"]) <= 256
        or not re.fullmatch(r"[a-f0-9]{64}", body["definition_fingerprint"])
        or (copy and not valid_copy_name(body["gateway_copy"]))
    ):
        raise ValueError()
    return body


@never_cache
@runtime_bearer_only
@api_view(["POST"])
@authentication_classes([GatewayTransportAuthentication])
@permission_classes([IsAuthenticated])
def provider_token(request, *, installed=False):
    """Trusted native adapter only: no public model/listener is activated here."""
    try:
        body = metadata(request, copy=installed and per_copy_check())
    except (ValueError, UnicodeError):
        return Response({"error": "invalid_request"}, status=400)
    try:
        if installed:
            if os.environ.get("GATEWAY_MODE", "managed") != "managed":
                raise ModelPolicyUnavailable("Managed runtime installation is required")
            installed_gate(
                body,
                MODEL_GATEWAY,
                settings.RUNTIME_GUARD_MANIFEST_FILE,
                os.environ.get("PROVIDER_KEY_DIR", ""),
                MODEL_GATEWAY_COPIES,
            ).require_installed(body["model_id"], body["definition_fingerprint"])
        credential = DjangoPersonalDispatch(
            RuntimeIdentity(IDENTITY),
            model_policy(),
            MODEL_GATEWAY,
            os.environ.get("PROVIDER_KEY_DIR", ""),
            project_access=organization_project_access,
        ).resolve(
            body["subject_token"],
            body["project_id"],
            body["model_id"],
            definition_fingerprint=body["definition_fingerprint"],
        )
    except ModelAccessDenied:
        return Response({"error": "invalid_grant"}, status=400)
    except (ModelPolicyUnavailable, StorageUnavailable):
        return Response({"error": "temporarily_unavailable"}, status=503)
    response = Response(
        {
            "access_token": credential.for_provider(),
            "token_type": "Bearer",
            "issued_token_type": ACCESS_TYPE,
        }
    )
    response["Pragma"] = "no-cache"
    return response
