"""Serve the single React application and explicit health endpoints."""

import logging
import mimetypes
import os

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import FileResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_GET

from .api import MODEL_GATEWAY, actor, admin
from .credential_check import KEY_REFUSED
from .readiness import schema_ready

log = logging.getLogger(__name__)


def gateway_runtime(log_refusal=False):
    """Read the gateway's runtime API; say plainly when it refuses the admin key."""
    status, result = MODEL_GATEWAY.request("/api/runtime", timeout=10)
    if status in (401, 403):
        # Typically a key rotation half done: the mounted admin key and the
        # gateway's loaded hash differ. Never pass the gateway's 401 on: the
        # admin's browser would read it as their own sign-in having ended.
        # Only the signed-in admin path logs, so public /health probes can't
        # fill the log.
        if log_refusal:
            log.warning("%s (HTTP %s)", KEY_REFUSED, status)
        return 503, {"error": KEY_REFUSED}
    return status, result


@require_GET
def application(request):
    if (
        os.environ.get("FIRST_ADMIN_PASSWORD_FILE")
        and not request.path.startswith("/app")
        and request.path != "/sign-in"
    ):
        user = actor(request)
        if not user:
            return HttpResponseRedirect("/sign-in")
        if user["role"] == "developer" and request.path not in {"/app", "/app/"}:
            return HttpResponseRedirect("/app/")
    redirects = {
        "/users": "/app/",
        "/models": "/app/models",
        "/data-classes": "/app/data-classes",
        "/audit": "/app/audit",
    }
    if request.path in redirects:
        return HttpResponseRedirect(redirects[request.path])
    index = settings.ADMIN_UI_DIR / "dist/index.html"
    if not index.is_file():
        return JsonResponse({"error": "Admin UI build is unavailable"}, status=503)
    response = FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def asset(request, asset):
    # Django resolves only these explicit public roots; no component routes proxy.
    folder = "fonts" if "/fonts/" in request.path else "assets"
    root = (settings.ADMIN_UI_DIR / "dist" / folder).resolve()
    file = (root / asset).resolve()
    if root not in file.parents or not file.is_file():
        return JsonResponse({"error": "Not found"}, status=404)
    return FileResponse(
        file.open("rb"),
        content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream",
    )


@require_GET
def app_health(request):
    return JsonResponse({"app": "ready"})


@require_GET
def readiness(request):
    try:
        if not schema_ready(connection):
            return JsonResponse({"app": "unavailable"}, status=503)
        if settings.CLI_OAUTH_ENABLED:
            from accounts.oauth_views import CLIENT_ID, DEVICE_ID, fixed_client

            if not all(fixed_client(name, lock=False) for name in (CLIENT_ID, DEVICE_ID)):
                return JsonResponse({"app": "unavailable"}, status=503)
    except DatabaseError:
        return JsonResponse({"app": "unavailable"}, status=503)
    # An installed detector is still loading its language model: keep this
    # copy out of service until it can check requests (bounded; see
    # personal_data.inspection.START_WAIT_SECONDS).
    from personal_data.inspection import detection_starting

    if detection_starting():
        return JsonResponse({"app": "starting"}, status=503)
    return JsonResponse({"app": "ready"})


@require_GET
def gateway_health(request):
    status, _ = gateway_runtime()
    return JsonResponse(
        {"gateway": "ready" if status == 200 else "unavailable"},
        status=200 if status == 200 else 503,
    )


@require_GET
def gateway_status(request):
    _, denied = admin(request)
    if denied:
        return JsonResponse(denied.data, status=denied.status_code)
    status, result = gateway_runtime(log_refusal=True)
    return JsonResponse(
        {
            "gateway": {
                "name": "agentgateway",
                "version": result.get("build", {}).get("version", "unknown"),
            }
        }
        if status == 200
        else result,
        status=status,
    )
