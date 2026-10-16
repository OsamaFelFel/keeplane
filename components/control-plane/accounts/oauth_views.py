"""Optional browser authorization; grant/token protocol stays in Toolkit."""

import json
import re
from urllib.parse import urlencode, urlsplit

from common.api import IDENTITY
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse, QueryDict
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .cli_credentials import checksum
from .models import SessionOwner, User

CLIENT_ID = "keeplane-cli"
DEVICE_ID = "keeplane-cli-device"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
AUTH_FIELDS = {
    "client_id",
    "response_type",
    "scope",
    "state",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "allow",
}


def unavailable():
    if not settings.CLI_OAUTH_ENABLED:
        return JsonResponse({"error": "not_found"}, status=404)
    origin = urlsplit(settings.PUBLIC_ORIGIN)
    if origin.scheme != "https" and not (
        origin.scheme == "http" and origin.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        return JsonResponse({"error": "temporarily_unavailable"}, status=503)


def parameters(request, fields):
    source = request.GET if request.method == "GET" else request.POST
    if len(source) > 16 or any(len(values) != 1 for _, values in source.lists()):
        raise ValueError
    clean = QueryDict(mutable=True)
    for name in fields & source.keys():
        clean[name] = source[name]
    # Ignore unsupported extensions; they cannot alter the issued authority.
    if request.method == "GET":
        request.GET = clean
        request.META["QUERY_STRING"] = clean.urlencode()
    else:
        request.POST = clean
        request.META["QUERY_STRING"] = ""
    return clean


def loopback_redirect(value):
    if not isinstance(value, str) or any(ord(c) < 33 or ord(c) > 126 for c in value):
        return False
    url = urlsplit(value)
    return (
        url.scheme == "http"
        and url.hostname == "127.0.0.1"
        and url.username is None
        and url.password is None
        and 0 < (url.port or 0) < 65536
        and url.path == "/callback"
        and not url.query
        and not url.fragment
    )


def fixed_client(client_id=CLIENT_ID, *, lock=True):
    from oauth2_provider.models import Application

    if client_id not in {CLIENT_ID, DEVICE_ID}:
        return False
    clients = Application.objects.select_for_update() if lock else Application.objects
    client = clients.filter(client_id=client_id).first()
    return client is not None and (
        client.client_type == client.CLIENT_PUBLIC
        and client.authorization_grant_type
        == (
            client.GRANT_AUTHORIZATION_CODE
            if client_id == CLIENT_ID
            else client.GRANT_DEVICE_CODE
        )
        and client.redirect_uris
        == ("http://127.0.0.1/callback" if client_id == CLIENT_ID else "")
        and not client.skip_authorization
        and not client.allowed_origins
        and not client.algorithm
    )


def token_response(response):
    if response.status_code == 200:
        return response
    error = json.loads(response.content).get("error", "invalid_request")
    known = {
        "invalid_grant",
        "invalid_request",
        "invalid_client",
        "invalid_scope",
        "authorization_pending",
        "slow_down",
        "access_denied",
        "expired_token",
    }
    return JsonResponse(
        {"error": error if error in known else "invalid_request"}, status=400
    )


@never_cache
@require_http_methods(["GET", "POST"])
def authorize(request):
    if denied := unavailable():
        return denied
    if (
        request.method == "POST"
        and request.content_type != "application/x-www-form-urlencoded"
    ):
        return JsonResponse({"error": "invalid_request"}, status=415)
    if len(request.META.get("QUERY_STRING", "")) > 4096 or len(request.body) > 4096:
        return JsonResponse({"error": "invalid_request"}, status=413)
    try:
        data = parameters(request, AUTH_FIELDS)
        if (
            data.get("client_id") != CLIENT_ID
            or data.get("response_type") != "code"
            or data.get("scope") != "runtime"
            or not loopback_redirect(data.get("redirect_uri"))
            or data.get("code_challenge_method") != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", data.get("code_challenge", ""))
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", data.get("state", ""))
        ):
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid_request"}, status=400)
    token = request.COOKIES.get("keeplane_session", "")
    if len(token) > 200:
        token = ""
    owner_id = (
        SessionOwner.objects.filter(session_id=token)
        .values_list("user_id", flat=True)
        .first()
    )
    with transaction.atomic():
        owner = User.objects.select_for_update().filter(pk=owner_id).first()
        current = IDENTITY.authenticated_user(token) if owner else None
        if current is None or current.pk != owner.pk:
            query = {key: data[key] for key in data if key != "allow"}
            return HttpResponseRedirect(
                "/sign-in?"
                + urlencode({"return_to": "/oauth/authorize/?" + urlencode(query)})
            )
        if not fixed_client():
            return JsonResponse({"error": "invalid_client"}, status=400)
        request.user, request.session = owner, SessionStore(session_key=token)
        from .oauth_validator import KeeplaneAuthorizationView

        return KeeplaneAuthorizationView.as_view()(request)


@never_cache
@require_POST
@sensitive_post_parameters("code", "code_verifier", "refresh_token", "device_code")
def token(request):
    if denied := unavailable():
        return denied
    if request.content_type != "application/x-www-form-urlencoded":
        return JsonResponse({"error": "invalid_request"}, status=415)
    if len(request.body) > 4096:
        return JsonResponse({"error": "invalid_request"}, status=413)
    if request.GET or request.headers.get("Authorization"):
        return JsonResponse({"error": "invalid_request"}, status=400)
    try:
        data = parameters(
            request,
            {
                "grant_type",
                "client_id",
                "code",
                "code_verifier",
                "redirect_uri",
                "refresh_token",
                "scope",
                "device_code",
            },
        )
        if (
            data.get("client_id") not in {CLIENT_ID, DEVICE_ID}
            or data.get("scope", "runtime") != "runtime"
        ):
            raise ValueError
        from oauth2_provider.models import Grant, RefreshToken

        from .oauth_validator import KeeplaneTokenView

        client_id = data["client_id"]
        if data.get("grant_type") == DEVICE_GRANT:
            if client_id != DEVICE_ID or not re.fullmatch(
                r"[A-Za-z0-9_-]{16,100}", data.get("device_code", "")
            ):
                raise ValueError
            from .oauth_device_protocol import DeviceTokenView

            return token_response(DeviceTokenView.as_view()(request))
        if data.get("grant_type") == "authorization_code":
            if (
                client_id != CLIENT_ID
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", data.get("code", ""))
                or not re.fullmatch(
                    r"[A-Za-z0-9._~-]{43,128}", data.get("code_verifier", "")
                )
                or not loopback_redirect(data.get("redirect_uri"))
            ):
                raise ValueError
            source = Grant.objects.filter(
                code=data["code"], application__client_id=CLIENT_ID
            )
        elif data.get("grant_type") == "refresh_token":
            if not re.fullmatch(
                r"[A-Za-z0-9_-]{16,200}", data.get("refresh_token", "")
            ):
                raise ValueError
            source = RefreshToken.objects.filter(
                token_checksum=checksum(data["refresh_token"]),
                application__client_id=client_id,
            )
        else:
            raise ValueError
        owner_id = source.values_list("user_id", flat=True).first()
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid_request"}, status=400)
    with transaction.atomic():
        owner = User.objects.select_for_update().filter(pk=owner_id).first()
        if owner is None or not owner.is_active:
            return JsonResponse({"error": "invalid_grant"}, status=400)
        if not fixed_client(client_id):
            return JsonResponse({"error": "invalid_client"}, status=400)
        return token_response(KeeplaneTokenView.as_view()(request))
