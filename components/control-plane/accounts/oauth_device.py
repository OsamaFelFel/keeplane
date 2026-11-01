"""Optional device routes; cookie approval and explicit grants stay separate."""

import re
from urllib.parse import urlencode

from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from . import oauth_views
from .cli_device_pages import rejected_code_context, rejected_confirm_context
from .contracts import LoginThrottled
from .models import SessionOwner, User


def budget(bucket):
    try:
        oauth_views.IDENTITY.reserve_login(bucket)
    except LoginThrottled as error:
        response = JsonResponse({"error": "temporarily_unavailable"}, status=429)
        response["Retry-After"] = str(error.retry_after)
        return response


@never_cache
@require_POST
def start(request):
    if denied := oauth_views.unavailable():
        return denied
    if request.content_type != "application/x-www-form-urlencoded":
        return JsonResponse({"error": "invalid_request"}, status=415)
    if len(request.body) > 4096:
        return JsonResponse({"error": "invalid_request"}, status=413)
    try:
        if request.GET or request.headers.get("Authorization"):
            raise ValueError
        data = oauth_views.parameters(request, {"client_id", "scope"})
        if (
            data.get("client_id") != oauth_views.DEVICE_ID
            or data.get("scope") != "runtime"
        ):
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "invalid_request"}, status=400)
    # Direct-peer address only; forwarded headers cannot acquire fresh budgets.
    if denied := budget("cli-device-peer:" + request.META.get("REMOTE_ADDR", "")[:128]):
        return denied
    from .oauth_device_protocol import DeviceStartView

    with transaction.atomic():
        if not oauth_views.fixed_client(oauth_views.DEVICE_ID):
            return JsonResponse({"error": "invalid_client"}, status=400)
        return DeviceStartView.as_view()(request)


@never_cache
@require_http_methods(["GET", "POST"])
def confirm(request):
    if denied := oauth_views.unavailable():
        return denied
    if (
        request.method == "POST"
        and request.content_type != "application/x-www-form-urlencoded"
    ):
        return JsonResponse({"error": "invalid_request"}, status=415)
    if len(request.body) > 4096 or len(request.META.get("QUERY_STRING", "")) > 4096:
        return JsonResponse({"error": "invalid_request"}, status=413)
    try:
        data = oauth_views.parameters(request, {"user_code", "stage", "action"})
        stage, code = data.get("stage", "entry"), data.get("user_code", "")
        if stage not in {"entry", "confirm"}:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "invalid_request"}, status=400)
    token = request.COOKIES.get("keeplane_session", "")
    token = token if len(token) <= 200 else ""
    owner_id = (
        SessionOwner.objects.filter(session_id=token)
        .values_list("user_id", flat=True)
        .first()
    )
    from oauth2_provider.models import DeviceGrant
    from oauth2_provider.views.device import DeviceGrantForm

    from .oauth_device_protocol import DeviceCodeView, DeviceConsentView

    with transaction.atomic():
        owner = User.objects.select_for_update().filter(pk=owner_id).first()
        current = oauth_views.IDENTITY.authenticated_user(token) if owner else None
        if current is None or current.pk != owner.pk:
            return HttpResponseRedirect(
                "/sign-in?"
                + urlencode(
                    {
                        "return_to": "/oauth/confirm-device/?"
                        + urlencode({"user_code": code, "stage": stage})
                    }
                )
            )
        if not oauth_views.fixed_client(oauth_views.DEVICE_ID):
            return JsonResponse({"error": "invalid_client"}, status=400)
        request.user = owner
        if (
            request.method == "POST"
            and stage == "entry"
            and (denied := budget("cli-device-owner:" + str(owner.pk)))
        ):
            return denied
        if request.method == "POST" or stage == "confirm":
            rows = DeviceGrant.objects.select_for_update().filter(user_code=code)
            device = (
                rows.first()
                if re.fullmatch(r"[0-9A-V]{8}", code) and rows.count() == 1
                else None
            )
            if (
                device is None
                or device.client_id != oauth_views.DEVICE_ID
                or device.scope != "runtime"
                or device.status != DeviceGrant.AUTHORIZATION_PENDING
                or device.is_expired()
                or device.user_id not in {None, owner.pk}
                or (stage == "confirm" and device.user_id != owner.pk)
            ):
                return render(
                    request,
                    "accounts/cli_device.html",
                    rejected_confirm_context(code)
                    if stage == "confirm"
                    else rejected_code_context(DeviceGrantForm, code),
                    status=400,
                )
        if stage == "confirm":
            return DeviceConsentView.as_view()(
                request, client_id=oauth_views.DEVICE_ID, user_code=code
            )
        return DeviceCodeView.as_view()(request)
