"""Account transport, using the local account use cases during cutover."""

import os

from django.utils.functional import SimpleLazyObject
from rest_framework.response import Response

from audit.contracts import AuditError
from data_classes.contracts import DataClassError
from integrations.gateway.adapter import AgentgatewayModelAdapter
from accounts.contracts import IdentityError, LoginThrottled
from common.stores import stores
from common.errors import StorageUnavailable


# Management commands validate URLs before initial migrations exist. Resolving
# a route must not bootstrap an account or query any application table.
AUDIT = SimpleLazyObject(lambda: stores()[0])
IDENTITY = SimpleLazyObject(lambda: stores()[1])
CATALOG = SimpleLazyObject(lambda: stores()[2])
DATA_CLASSES = SimpleLazyObject(lambda: stores()[3])
MODEL_GATEWAY = AgentgatewayModelAdapter(
    os.environ.get("GATEWAY_URL", "http://gateway:4000"),
    os.environ.get("GATEWAY_RUNTIME_KEY_FILE", ""),
    os.environ.get("GATEWAY_ADMIN_KEY_FILE", ""),
)
RUNNER_URLS = {
    url.strip().rstrip("/")
    for url in os.environ.get("PREVIEW_RUNNER_URLS", "http://qwen:8080").split(",")
    if url.strip()
}
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "")
PUBLIC_ORIGIN_ALIASES = {
    part.strip()
    for part in os.environ.get("PUBLIC_ORIGIN_ALIASES", "").split(",")
    if part.strip()
}


def failure(status, message):
    return Response({"error": message}, status=status)


def result(action):
    try:
        return action()
    except LoginThrottled as error:
        response = failure(error.status, error.message)
        response["Retry-After"] = str(error.retry_after)
        return response
    except IdentityError as error:
        return failure(error.status, error.message)
    except StorageUnavailable:
        return failure(503, "Account storage is unavailable")


def settings_result(action):
    try:
        return action()
    except (DataClassError, AuditError) as error:
        return failure(error.status, error.message)
    except StorageUnavailable:
        return failure(503, "Keeplane settings storage is unavailable")


def actor(request):
    token = request.COOKIES.get("keeplane_session", "")
    return IDENTITY.session(token)


def admin(request):
    user = actor(request)
    return user, None if user and user["role"] == "admin" else failure(
        403 if user else 401, "Admin access required" if user else "Sign in to Keeplane"
    )


def trusted_origin(request):
    origin = request.headers.get("Origin")
    return not origin or origin in {PUBLIC_ORIGIN, *PUBLIC_ORIGIN_ALIASES}


def action_allowed(request):
    return (
        request.headers.get("X-Keeplane-Action") == "1"
        and request.content_type == "application/json"
        and trusted_origin(request)
    )


def action_error(request):
    if not action_allowed(request):
        return failure(403, "Changes require Keeplane's admin UI")
    return (
        None if isinstance(request.data, dict) else failure(400, "Enter a JSON object")
    )
