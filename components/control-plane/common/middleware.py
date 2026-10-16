"""Protect browser requests before they reach the administration API."""

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.deprecation import MiddlewareMixin

from .errors import StorageUnavailable


class StorageFailureMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        if isinstance(exception, (StorageUnavailable, DatabaseError)):
            response = JsonResponse(
                {"error": "Keeplane storage is unavailable; contact your operator"},
                status=503,
            )
            response["Cache-Control"] = "no-store"
            return response
        if isinstance(exception, RequestDataTooBig):
            return JsonResponse({"error": "Request is too large"}, status=413)


class RequestLimitMiddleware(MiddlewareMixin):
    def process_request(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return JsonResponse({"error": "Invalid request length"}, status=400)
        if length < 0 or length > 64 * 1024:
            return JsonResponse({"error": "Request is too large"}, status=413)


class PublicSchemeMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # The public origin is operator configuration; forwarded client headers
        # cannot turn Django's HTTPS checks on or off.
        scheme = "https" if settings.PUBLIC_ORIGIN.startswith("https://") else "http"
        request.META["wsgi.url_scheme"] = scheme
        if hasattr(request, "scope"):
            request.scope["scheme"] = scheme


class BrowserCsrfMiddleware(CsrfViewMiddleware):
    def process_view(self, request, callback, callback_args, callback_kwargs):
        if getattr(callback, "runtime_bearer_only", False):
            from accounts.authentication import RuntimeSessionAuthentication
            from model_registry.personal_transport import GatewayTransportAuthentication
            from rest_framework.permissions import IsAuthenticated

            view = getattr(callback, "cls", None)
            if tuple(getattr(view, "authentication_classes", ())) in (
                (RuntimeSessionAuthentication,),
                (GatewayTransportAuthentication,),
            ) and tuple(getattr(view, "permission_classes", ())) == (IsAuthenticated,):
                # These views accept explicit header credentials only, never
                # ambient browser cookies. DRF still authenticates every call.
                return None
        # DRF's view exemption must not exempt anonymous sign-in or cookie writes.
        return super().process_view(request, None, callback_args, callback_kwargs)


def csrf_failure(request, reason=""):
    response = JsonResponse(
        {"error": "Reload Keeplane and try again.", "code": "csrf_failed"}, status=403
    )
    response["Cache-Control"] = "no-store"
    return response
