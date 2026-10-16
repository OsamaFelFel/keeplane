"""Bounded device lifecycle around maintained Toolkit protocol and browser views."""

from datetime import timedelta
from urllib.parse import urlencode

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from oauth2_provider.models import DeviceGrant
from oauth2_provider.views import (
    DeviceAuthorizationView,
    DeviceConfirmView,
    DeviceUserCodeView,
)

from .cli_credentials import bind_issued_token, checksum, current_binding
from .models import CliCredentialBinding, User
from .oauth_validator import KeeplaneOAuthValidator, KeeplaneTokenView
from .oauth_views import DEVICE_ID, fixed_client


def error(name):
    return JsonResponse({"error": name}, status=400)


class DeviceTokenView(KeeplaneTokenView):
    def device_flow_token_response(self, request, device_code, *args, **kwargs):
        owner_id = (
            DeviceGrant.objects.filter(device_code=device_code, client_id=DEVICE_ID)
            .values_list("user_id", flat=True)
            .first()
        )
        with transaction.atomic():
            owner = (
                User.objects.select_for_update().filter(pk=owner_id).first()
                if owner_id
                else None
            )
            if not fixed_client(DEVICE_ID):
                return error("invalid_client")
            device = (
                DeviceGrant.objects.select_for_update()
                .filter(device_code=device_code, client_id=DEVICE_ID, scope="runtime")
                .first()
            )
            if device is None:
                return error("invalid_grant")
            if device.user_id != owner_id:
                # Approval raced the locator. Retry with the owner first; never invert locks.
                return error("authorization_pending")
            if device.is_expired():
                return error("expired_token")
            if device.status == device.AUTHORIZED and not current_binding(
                CliCredentialBinding.Kind.DEVICE, device_code, owner
            ):
                return error("invalid_grant")
            if device.status in {device.AUTHORIZATION_PENDING, device.AUTHORIZED}:
                now = timezone.now()
                early = now < device.last_checked + timedelta(seconds=device.interval)
                DeviceGrant.objects.filter(pk=device.pk).update(
                    last_checked=now, interval=device.interval + (5 if early else 0)
                )
                if early:
                    return error("slow_down")
            response = super().device_flow_token_response(
                request, device_code, *args, **kwargs
            )
            if response.status_code == 200:
                # The validator has already bound both new tokens in this transaction.
                device.delete()
                CliCredentialBinding.objects.filter(
                    checksum=checksum(device_code), kind="device"
                ).delete()
            return response


class DeviceStartView(DeviceAuthorizationView):
    validator_class = KeeplaneOAuthValidator

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            import json

            value = json.loads(response.content)
            row = DeviceGrant.objects.get(device_code=value["device_code"])
            if (
                DeviceGrant.objects.filter(user_code=row.user_code)
                .exclude(pk=row.pk)
                .exists()
            ):
                row.delete()
                return JsonResponse({"error": "temporarily_unavailable"}, status=503)
            # Toolkit's create_device_grant does not copy the advertised interval.
            row.interval = value["interval"]
            row.save(update_fields=["interval"])
        return response


class DeviceCodeView(DeviceUserCodeView):
    template_name = "accounts/cli_device.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "entry": True}

    def get_success_url(self):
        return "/oauth/confirm-device/?" + urlencode(
            {"user_code": self.device_grant.user_code, "stage": "confirm"}
        )


class DeviceConsentView(DeviceConfirmView):
    template_name = "accounts/cli_device.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        if response.status_code != 302:
            return response
        device = self.get_object()
        allowed = device.status == device.AUTHORIZED
        if allowed:
            bind_issued_token(
                CliCredentialBinding.Kind.DEVICE,
                device.device_code,
                self.request.user.pk,
                self.request.user.get_session_auth_hash(),
            )
        return render(
            self.request, self.template_name, {"complete": True, "allowed": allowed}
        )

    def get_success_url(self):
        # The response is rendered above before the CLI can consume the source.
        return "/oauth/confirm-device/"

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            "user_code": self.kwargs["user_code"],
        }
