"""Actual maintained device flow plus Keeplane lifecycle/account boundaries."""

import re
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from accounts.models import CliCredentialBinding
from django.apps import apps
from django.core.management import call_command
from django.utils import timezone

from tests.integration.test_cli_oauth_browser import FORM, browser_flow  # noqa: F401

pytestmark = [
    pytest.mark.optional,
    pytest.mark.live,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not apps.is_installed("oauth2_provider"),
        reason="Install the pinned OAuth trial graph",
    ),
]


@pytest.fixture
def device(browser_flow):  # noqa: F811
    from oauth2_provider.models import DeviceGrant

    flow = browser_flow
    call_command("register_cli_client", device=True, verbosity=0)

    def start():
        response = flow.anonymous.post(
            "/oauth/device/",
            urlencode({"client_id": "keeplane-cli-device", "scope": "runtime"}),
            content_type=FORM,
        )
        assert response.status_code == 200, response.content
        value = response.json()
        assert value["interval"] == 5
        assert value["verification_uri"].endswith("/oauth/confirm-device/")
        return SimpleNamespace(
            value=value, row=DeviceGrant.objects.get(device_code=value["device_code"])
        )

    def post(data, csrf=True):
        headers = {}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = flow.browser.get("/api/auth-options").json()[
                "csrf_token"
            ]
        return flow.browser.post(
            "/oauth/confirm-device/", urlencode(data), content_type=FORM, **headers
        )

    def approve(issued, action="accept"):
        response = post({"user_code": issued.value["user_code"]})
        assert response.status_code == 302, response.content
        page = flow.browser.get(response["Location"])
        assert page.status_code == 200 and b"Allow CLI access?" in page.content
        response = post(
            {
                "user_code": issued.value["user_code"],
                "stage": "confirm",
                "action": action,
            }
        )
        assert response.status_code == 200, response.content
        return response

    def due(issued):
        DeviceGrant.objects.filter(pk=issued.row.pk).update(
            last_checked=timezone.now() - timedelta(minutes=5)
        )

    def poll(issued, **overrides):
        return flow.anonymous.post(
            "/oauth/token/",
            urlencode(
                {
                    "client_id": "keeplane-cli-device",
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": issued.value["device_code"],
                    **overrides,
                }
            ),
            content_type=FORM,
        )

    return SimpleNamespace(
        flow=flow, start=start, post=post, approve=approve, due=due, poll=poll
    )


def test_device_real_approval_issue_consume_and_refresh(device):
    from oauth2_provider.models import AccessToken, DeviceGrant, RefreshToken

    issued = device.start()
    assert device.flow.browser.get("/oauth/confirm-device/").status_code == 200
    device.approve(issued)
    assert CliCredentialBinding.objects.filter(kind="device").count() == 1
    device.due(issued)
    response = device.poll(issued)
    assert response.status_code == 200, response.content
    value = response.json()
    assert device.flow.identity.session(value["access_token"])["id"] == str(
        device.flow.owner.pk
    )
    assert AccessToken.objects.get().token == RefreshToken.objects.get().token == ""
    assert (
        not DeviceGrant.objects.exists()
        and not CliCredentialBinding.objects.filter(kind="device").exists()
    )
    assert device.poll(issued).status_code == 400
    response = device.flow.anonymous.post(
        "/oauth/token/",
        urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": "keeplane-cli-device",
                "refresh_token": value["refresh_token"],
            }
        ),
        content_type=FORM,
    )
    assert response.status_code == 200, response.content
    rotated = response.json()
    assert (
        device.flow.anonymous.delete(
            "/api/runtime/session",
            HTTP_AUTHORIZATION="Bearer " + rotated["access_token"],
        ).status_code
        == 204
    )
    assert (
        device.flow.anonymous.post(
            "/oauth/token/",
            urlencode(
                {
                    "grant_type": "refresh_token",
                    "client_id": "keeplane-cli-device",
                    "refresh_token": rotated["refresh_token"],
                }
            ),
            content_type=FORM,
        ).status_code
        == 400
    )
    assert device.flow.browser.get("/api/identity").status_code == 200


def test_device_pending_cadence_and_increasing_slow_down(device):
    issued = device.start()
    device.due(issued)
    assert device.poll(issued).json() == {"error": "authorization_pending"}
    assert device.poll(issued).json() == {"error": "slow_down"}
    issued.row.refresh_from_db()
    assert issued.row.interval == 10
    assert device.poll(issued).json() == {"error": "slow_down"}
    issued.row.refresh_from_db()
    assert issued.row.interval == 15


def test_device_expired_and_denied_never_issue(device):
    from oauth2_provider.models import AccessToken, DeviceGrant

    expired = device.start()
    device.approve(expired)
    DeviceGrant.objects.filter(pk=expired.row.pk).update(
        expires=timezone.now() - timedelta(seconds=1)
    )
    assert device.poll(expired).json() == {"error": "expired_token"}
    denied = device.start()
    device.approve(denied, "deny")
    assert device.poll(denied).json() == {"error": "access_denied"}
    assert not AccessToken.objects.exists()


@pytest.mark.parametrize("withdrawal", ["global", "password", "disabled", "binding"])
def test_device_rechecks_live_approval_and_current_account(device, withdrawal):
    from accounts.models import User
    from accounts.services import revoke
    from oauth2_provider.models import AccessToken

    issued = device.start()
    device.approve(issued)
    owner = device.flow.owner
    if withdrawal == "global":
        revoke(owner)
    elif withdrawal == "password":
        owner.set_password("synthetic-new-device-password")
        owner.save(update_fields=["password"])
    elif withdrawal == "disabled":
        User.objects.filter(pk=owner.pk).update(is_active=False)
    else:
        CliCredentialBinding.objects.filter(kind="device").delete()
    assert device.poll(issued).json() == {"error": "invalid_grant"}
    assert not AccessToken.objects.exists()


def test_device_consent_retains_csrf_and_fresh_browser_session(device):
    from oauth2_provider.models import DeviceGrant

    issued = device.start()
    fields = {"user_code": issued.value["user_code"]}
    assert device.post(fields, csrf=False).status_code == 403
    assert device.post(fields).status_code == 302
    fields.update(stage="confirm", action="accept")
    assert device.post(fields, csrf=False).status_code == 403
    device.flow.native.logout(device.flow.browser.cookies["keeplane_session"].value)
    response = device.post(fields)
    assert response.status_code == 302 and response["Location"].startswith(
        "/sign-in?return_to="
    )
    assert DeviceGrant.objects.get().status == DeviceGrant.AUTHORIZATION_PENDING
    assert not CliCredentialBinding.objects.filter(kind="device").exists()


def assert_confirm_rejected(response, code):
    """A confirm-stage rejection keeps the confirm screen with its failure message."""
    html = response.content.decode()
    assert "Allow CLI access?" in html and f"<code>{code}</code>" in html
    assert re.search(
        r'<div class="alert" role="alert">.*'
        r"Check the code shown in your CLI and try again\.</p></div>\s*"
        r'<div class="actions">',
        html,
    )
    body = html[html.index("<main>") :]
    assert '<input type="text"' not in body and 'class="field-error"' not in body


def test_device_claim_cannot_be_stolen_or_confirmed_by_another_account(device):
    issued = device.start()
    fields = {"user_code": issued.value["user_code"]}
    unclaimed = device.post({**fields, "stage": "confirm", "action": "accept"})
    assert unclaimed.status_code == 400
    assert_confirm_rejected(unclaimed, issued.value["user_code"])
    assert device.post(fields).status_code == 302
    device.flow.native.create_user(
        {
            "username": "other-device-user",
            "role": "developer",
            "password": "synthetic-other-password",
        }
    )
    device.flow.sign_in("other-device-user", "synthetic-other-password")
    assert device.post(fields).status_code == 400
    rejected = device.post({**fields, "stage": "confirm", "action": "accept"})
    assert rejected.status_code == 400
    assert_confirm_rejected(rejected, issued.value["user_code"])
    issued.row.refresh_from_db()
    assert (
        issued.row.user_id == device.flow.owner.pk
        and not CliCredentialBinding.objects.filter(kind="device").exists()
    )


def test_device_client_and_scope_are_bound_before_token_creation(device):
    from oauth2_provider.models import AccessToken, DeviceGrant

    issued = device.start()
    device.approve(issued)
    device.due(issued)
    assert device.poll(issued, client_id="keeplane-cli").status_code == 400
    assert device.poll(issued, scope="other").status_code == 400
    DeviceGrant.objects.filter(pk=issued.row.pk).update(client_id="other-public-client")
    assert device.poll(issued).json() == {"error": "invalid_grant"}
    assert not AccessToken.objects.exists()


def test_device_binding_failure_rolls_back_pair_and_consumption(device, monkeypatch):
    from accounts import oauth_validator
    from django.db import DatabaseError
    from oauth2_provider.models import AccessToken, DeviceGrant, RefreshToken

    issued = device.start()
    device.approve(issued)
    device.due(issued)
    original = oauth_validator.bind_issued_token

    def fail_refresh(kind, *args):
        if kind == "refresh":
            raise DatabaseError("synthetic confidential device failure")
        return original(kind, *args)

    with monkeypatch.context() as patch:
        patch.setattr(oauth_validator, "bind_issued_token", fail_refresh)
        response = device.poll(issued)
    assert response.status_code == 503 and b"confidential" not in response.content
    assert not AccessToken.objects.exists() and not RefreshToken.objects.exists()
    assert DeviceGrant.objects.get().status == DeviceGrant.AUTHORIZED
    assert CliCredentialBinding.objects.filter(kind="device").count() == 1
    assert device.poll(issued).status_code == 200


def test_pending_approval_race_defers_without_acquiring_owner_after_device(
    device, monkeypatch
):
    from accounts.models import User
    from oauth2_provider.models import AccessToken, DeviceGrant

    issued = device.start()
    device.due(issued)
    select_device = DeviceGrant.objects.select_for_update
    select_owner = User.objects.select_for_update
    changed, locks = [], []

    def owner(*args, **kwargs):
        locks.append("owner")
        return select_owner(*args, **kwargs)

    def approve_before_device(*args, **kwargs):
        if not changed:
            changed.append(True)
            device.approve(issued)
            locks.clear()
        locks.append("device")
        return select_device(*args, **kwargs)

    monkeypatch.setattr(User.objects, "select_for_update", owner)
    monkeypatch.setattr(DeviceGrant.objects, "select_for_update", approve_before_device)
    assert device.poll(issued).json() == {"error": "authorization_pending"}
    assert locks == ["device"] and not AccessToken.objects.exists()
    locks.clear()
    assert device.poll(issued).status_code == 200
    assert locks.index("owner") < locks.index("device")


def test_device_code_guessing_and_anonymous_initiation_have_separate_budgets(device):
    for _ in range(5):
        device.start()
    response = device.flow.anonymous.post(
        "/oauth/device/",
        urlencode({"client_id": "keeplane-cli-device", "scope": "runtime"}),
        content_type=FORM,
        HTTP_X_FORWARDED_FOR="192.0.2.10",
    )
    assert response.status_code == 429 and 1 <= int(response["Retry-After"]) <= 60
    for _ in range(5):
        assert device.post({"user_code": "INVALID1"}).status_code == 400
    assert device.post({"user_code": "INVALID2"}).status_code == 429


def test_device_rejected_code_marks_the_field_and_links_its_error(device):
    page = device.post({"user_code": "INVALID1"})
    assert page.status_code == 400
    html = page.content.decode()
    field = re.search(r'<input type="text" name="user_code"[^>]*>', html).group(0)
    assert 'aria-invalid="true"' in field
    assert 'aria-describedby="id_user_code_error"' in field
    assert re.search(
        r'<p class="field-error" id="id_user_code_error">.*'
        r"Check the code shown in your CLI and try again\.",
        html,
    )


def test_device_collision_refuses_new_source_and_keeps_original(device):
    from django.conf import settings
    from django.test import override_settings
    from oauth2_provider.models import DeviceGrant

    options = {
        **settings.OAUTH2_PROVIDER,
        "OAUTH_DEVICE_USER_CODE_GENERATOR": lambda: "ABCD1234",
    }
    with override_settings(OAUTH2_PROVIDER=options):
        device.start()
        response = device.flow.anonymous.post(
            "/oauth/device/",
            urlencode({"client_id": "keeplane-cli-device", "scope": "runtime"}),
            content_type=FORM,
        )
    assert response.status_code == 503 and DeviceGrant.objects.count() == 1


def test_device_persisted_interval_matches_advertised_value(device):
    from django.conf import settings
    from django.test import override_settings
    from oauth2_provider.models import DeviceGrant

    with override_settings(
        OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "DEVICE_FLOW_INTERVAL": 11}
    ):
        response = device.flow.anonymous.post(
            "/oauth/device/",
            urlencode({"client_id": "keeplane-cli-device", "scope": "runtime"}),
            content_type=FORM,
        )
    assert response.status_code == 200
    assert response.json()["interval"] == DeviceGrant.objects.get().interval == 11


def test_device_approval_binding_failure_rolls_back_status(device, monkeypatch):
    from accounts import oauth_device_protocol
    from django.db import DatabaseError
    from oauth2_provider.models import DeviceGrant

    issued = device.start()
    assert device.post({"user_code": issued.value["user_code"]}).status_code == 302

    def fail(*args):
        raise DatabaseError("synthetic confidential approval error")

    fields = {
        "user_code": issued.value["user_code"],
        "stage": "confirm",
        "action": "accept",
    }
    with monkeypatch.context() as patch:
        patch.setattr(oauth_device_protocol, "bind_issued_token", fail)
        response = device.post(fields)
    assert response.status_code == 503 and b"confidential" not in response.content
    assert DeviceGrant.objects.get().status == DeviceGrant.AUTHORIZATION_PENDING
    assert not CliCredentialBinding.objects.filter(kind="device").exists()
    assert device.post(fields).status_code == 200


def test_device_routes_keep_trial_transport_and_fixed_client_gates(device):
    from django.test import override_settings
    from oauth2_provider.models import Application, DeviceGrant

    payload = urlencode({"client_id": "keeplane-cli-device", "scope": "runtime"})
    for options in (
        {"CLI_OAUTH_ENABLED": False},
        {"PUBLIC_ORIGIN": "http://foreign.invalid"},
    ):
        with override_settings(**options):
            response = device.flow.anonymous.post(
                "/oauth/device/", payload, content_type=FORM
            )
            assert response.status_code in {403, 404, 503}
            assert device.flow.browser.get("/oauth/confirm-device/").status_code in {
                404,
                503,
            }
    Application.objects.filter(client_id="keeplane-cli-device").update(
        skip_authorization=True
    )
    assert device.flow.anonymous.post(
        "/oauth/device/", payload, content_type=FORM
    ).json() == {"error": "invalid_client"}
    assert not DeviceGrant.objects.exists()


@pytest.mark.parametrize("change", ["duplicate", "query", "scope", "client", "large"])
def test_device_start_refuses_ambiguous_or_excessive_requests(device, change):
    from oauth2_provider.models import DeviceGrant

    fields = [("client_id", "keeplane-cli-device"), ("scope", "runtime")]
    path = "/oauth/device/"
    if change == "duplicate":
        fields.append(("client_id", "keeplane-cli-device"))
    elif change == "query":
        path += "?scope=runtime"
    elif change == "scope":
        fields[1] = ("scope", "other")
    elif change == "client":
        fields[0] = ("client_id", "keeplane-cli")
    else:
        fields.append(("untrusted", "x" * 4096))
    response = device.flow.anonymous.post(path, urlencode(fields), content_type=FORM)
    assert response.status_code in {400, 413} and not DeviceGrant.objects.exists()
