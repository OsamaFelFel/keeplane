"""Serve the single React application and explicit health endpoints."""

import mimetypes
import os
from django.conf import settings
from django.db import DatabaseError, connection
from django.http import FileResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_GET
from .api import MODEL_GATEWAY, actor, admin
from .readiness import schema_ready


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
    except DatabaseError:
        return JsonResponse({"app": "unavailable"}, status=503)
    return JsonResponse({"app": "ready"})


@require_GET
def gateway_health(request):
    status, _ = MODEL_GATEWAY.request("/api/runtime", timeout=10)
    return JsonResponse(
        {"gateway": "ready" if status == 200 else "unavailable"},
        status=200 if status == 200 else 503,
    )


@require_GET
def gateway_status(request):
    _, denied = admin(request)
    if denied:
        return JsonResponse(denied.data, status=denied.status_code)
    status, result = MODEL_GATEWAY.request("/api/runtime", timeout=10)
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
