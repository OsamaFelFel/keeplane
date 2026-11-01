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


# Gateway request checks may carry the request's messages for personal-data
# detection (Spec 005 ST20); the views bound what they read to the same limit.
CHECK_PATHS = frozenset({
    "/internal/runtime/authorize",
    "/internal/runtime/authorize/selected",
    "/internal/runtime/installed/entry",
    "/internal/runtime/installed/selected",
})
CHECK_LIMIT = 8 * 1024 * 1024


class RequestLimitMiddleware(MiddlewareMixin):
    def process_request(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return JsonResponse({"error": "Invalid request length"}, status=400)
        limit = CHECK_LIMIT if request.path in CHECK_PATHS else 64 * 1024
        if length < 0 or length > limit:
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
        from accounts import oauth_device, oauth_views

        if (
            callback in (oauth_views.token, oauth_device.start)
            and settings.CLI_OAUTH_ENABLED
            and request.method == "POST"
            and request.content_type == "application/x-www-form-urlencoded"
        ):
            # Only the dedicated grant endpoint: cookies never authenticate it.
            return None
        if getattr(callback, "runtime_bearer_only", False):
            from accounts.authentication import RuntimeSessionAuthentication
            from model_registry.runtime_callback import OperatorValidationAuthentication
            from model_registry.personal_transport import GatewayTransportAuthentication
            from rest_framework.permissions import IsAuthenticated

            view = getattr(callback, "cls", None)
            if tuple(getattr(view, "authentication_classes", ())) in (
                (RuntimeSessionAuthentication,),
                (OperatorValidationAuthentication,),
                (GatewayTransportAuthentication,),
            ) and tuple(getattr(view, "permission_classes", ())) == (IsAuthenticated,):
                # These views accept an explicit bearer credential only, never
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
