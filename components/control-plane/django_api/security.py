"""Django CSRF checks also cover anonymous sign-in and DRF browser endpoints."""

from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware


class BrowserCsrfMiddleware(CsrfViewMiddleware):
    def process_view(self, request, callback, callback_args, callback_kwargs):
        # DRF exempts its views in favor of SessionAuthentication. During the
        # account cutover our cookie sessions need the same checks, including
        # before sign-in. All routes on this listener are browser routes.
        return super().process_view(request, None, callback_args, callback_kwargs)


def csrf_failure(request, reason=""):
    response = JsonResponse({"error": "Reload Keeplane and try again.",
                             "code": "csrf_failed"}, status=403)
    response["Cache-Control"] = "no-store"
    return response
