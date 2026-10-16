"""Actual Toolkit/Django browser and token transport with synthetic accounts."""

import base64
import hashlib
import secrets
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from accounts import authentication, oauth_views, views
from accounts.cli_credentials import RuntimeIdentity
from accounts.models import CliCredentialBinding, User
from accounts.services import revoke
from common import api
from django.apps import apps
from django.core.management import call_command
from django.test import Client, override_settings
from model_registry import runtime_views

pytestmark = [
    pytest.mark.optional,
    pytest.mark.live,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not apps.is_installed("oauth2_provider"),
        reason="Install the pinned OAuth trial graph",
    ),
]
FORM = "application/x-www-form-urlencoded"
ORIGIN = "http://127.0.0.1:3000"


@pytest.fixture
def browser_flow(domain_services, monkeypatch):
    native = domain_services.identity
    native.create_user(
        {
            "username": "browser-developer",
            "role": "developer",
            "password": "synthetic-browser-password",
        }
    )
    owner = User.objects.get(username="browser-developer")
    for module in (api, views, authentication, oauth_views, runtime_views):
        monkeypatch.setattr(module, "IDENTITY", native)
    monkeypatch.setattr(api, "PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setattr(views, "PUBLIC_ORIGIN", ORIGIN)
    call_command("register_cli_client", verbosity=0)
    browser = Client(
        enforce_csrf_checks=True, HTTP_HOST="127.0.0.1:3000", HTTP_ORIGIN=ORIGIN
    )
    anonymous = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1:3000")

    def sign_in(username="browser-developer", password="synthetic-browser-password"):
        csrf = browser.get("/api/auth-options").json()["csrf_token"]
        response = browser.post(
            "/api/session",
            {"username": username, "password": password},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        assert response.status_code == 200

    def code(overrides=None, *, allow=True):
        verifier = secrets.token_urlsafe(32)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        parameters = {
            "client_id": "keeplane-cli",
            "response_type": "code",
            "scope": "runtime",
            "redirect_uri": "http://127.0.0.1:62431/callback",
            "state": secrets.token_urlsafe(32),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        parameters.update(overrides or {})
        consent = browser.get("/oauth/authorize/", parameters)
        assert consent.status_code == 200, consent.content
        fields = {
            key: value
            for key, value in consent.context_data["form"].initial.items()
            if value is not None
        }
        if allow:
            fields["allow"] = "true"
        csrf = browser.get("/api/auth-options").json()["csrf_token"]
        response = browser.post(
            "/oauth/authorize/",
            urlencode(fields),
            content_type=FORM,
            HTTP_X_CSRFTOKEN=csrf,
        )
        assert response.status_code == 302, response.content
        returned = parse_qs(urlsplit(response["Location"]).query)
        assert returned["state"] == [parameters["state"]]
        return SimpleNamespace(
            parameters=parameters, verifier=verifier, returned=returned
        )

    def exchange(issued, overrides=None):
        data = {
            "grant_type": "authorization_code",
            "client_id": "keeplane-cli",
            "code": issued.returned["code"][0],
            "code_verifier": issued.verifier,
            "redirect_uri": issued.parameters["redirect_uri"],
        }
        data.update(overrides or {})
        return anonymous.post("/oauth/token/", urlencode(data), content_type=FORM)

    def refresh(value):
        return anonymous.post(
            "/oauth/token/",
            urlencode(
                {
                    "grant_type": "refresh_token",
                    "client_id": "keeplane-cli",
                    "refresh_token": value,
                }
            ),
            content_type=FORM,
        )

    with override_settings(
        CLI_OAUTH_ENABLED=True, ALLOWED_HOSTS=["127.0.0.1", "testserver"]
    ):
        sign_in()
        yield SimpleNamespace(
            native=native,
            owner=owner,
            browser=browser,
            anonymous=anonymous,
            sign_in=sign_in,
            code=code,
            exchange=exchange,
            refresh=refresh,
            identity=RuntimeIdentity(native),
            domain=domain_services,
        )


def test_real_consent_code_exchange_hashes_and_replay(browser_flow):
    from oauth2_provider.models import AccessToken, Grant, RefreshToken

    flow = browser_flow
    issued = flow.code()
    assert Grant.objects.count() == 1
    assert (
        CliCredentialBinding.objects.filter(kind="code", owner=flow.owner).count() == 1
    )
    assert issued.returned["iss"] == [ORIGIN]
    response = flow.exchange(issued)
    assert response.status_code == 200, response.content
    value = response.json()
    assert value["access_token"].startswith("kpc_") and value[
        "refresh_token"
    ].startswith("kpr_")
    assert AccessToken.objects.get().token == RefreshToken.objects.get().token == ""
    assert flow.identity.authenticated_user(value["access_token"]).pk == flow.owner.pk
    assert (
        not Grant.objects.exists()
        and not CliCredentialBinding.objects.filter(kind="code").exists()
    )
    assert flow.exchange(issued).status_code == 400
    assert "no-store" in response["Cache-Control"]


def test_wrong_verifier_and_redirect_do_not_consume_code(browser_flow):
    flow = browser_flow
    issued = flow.code()
    assert flow.exchange(issued, {"code_verifier": "wrong" * 12}).status_code == 400
    assert (
        flow.exchange(
            issued, {"redirect_uri": "http://127.0.0.1:62432/callback"}
        ).status_code
        == 400
    )
    assert flow.exchange(issued).status_code == 200


def test_cancel_returns_state_without_creating_a_grant(browser_flow):
    from oauth2_provider.models import Grant

    issued = browser_flow.code(allow=False)
    assert issued.returned["error"] == ["access_denied"]
    assert "code" not in issued.returned and not Grant.objects.exists()
    assert not CliCredentialBinding.objects.filter(kind="code").exists()


def test_refresh_rotation_replay_and_exact_pair_logout(browser_flow):
    flow = browser_flow
    first = flow.exchange(flow.code()).json()
    other = flow.exchange(flow.code()).json()
    rotated_response = flow.refresh(first["refresh_token"])
    assert rotated_response.status_code == 200, rotated_response.content
    rotated = rotated_response.json()
    assert flow.identity.session(first["access_token"]) is None
    assert flow.identity.session(rotated["access_token"]) is not None
    assert flow.refresh(first["refresh_token"]).status_code == 400
    assert flow.identity.session(rotated["access_token"]) is None
    assert flow.identity.session(other["access_token"]) is not None
    signed_out = flow.anonymous.delete(
        "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + other["access_token"]
    )
    assert signed_out.status_code == 204
    assert flow.refresh(other["refresh_token"]).status_code == 400
    assert flow.browser.get("/api/identity").status_code == 200


@pytest.mark.parametrize(
    "withdrawal", ["global", "password", "disabled", "binding", "expired"]
)
def test_code_rechecks_current_account_and_live_grant(browser_flow, withdrawal):
    from datetime import timedelta

    from django.utils import timezone
    from oauth2_provider.models import AccessToken, Grant

    flow = browser_flow
    issued = flow.code()
    if withdrawal == "global":
        revoke(flow.owner)
    elif withdrawal == "password":
        flow.owner.set_password("synthetic-changed-password")
        flow.owner.save(update_fields=["password"])
    elif withdrawal == "disabled":
        User.objects.filter(pk=flow.owner.pk).update(is_active=False)
    elif withdrawal == "binding":
        CliCredentialBinding.objects.filter(kind="code").delete()
    else:
        Grant.objects.update(expires=timezone.now() - timedelta(seconds=1))
    assert flow.exchange(issued).status_code == 400
    assert not AccessToken.objects.exists()


@pytest.mark.parametrize("withdrawal", ["global", "password", "disabled", "binding"])
def test_refresh_rechecks_current_account_and_binding(browser_flow, withdrawal):
    flow = browser_flow
    token = flow.exchange(flow.code()).json()
    if withdrawal == "global":
        revoke(flow.owner)
    elif withdrawal == "password":
        flow.owner.set_password("synthetic-changed-password")
        flow.owner.save(update_fields=["password"])
    elif withdrawal == "disabled":
        User.objects.filter(pk=flow.owner.pk).update(is_active=False)
    else:
        CliCredentialBinding.objects.filter(kind="refresh").delete()
    assert flow.refresh(token["refresh_token"]).status_code == 400


def test_browser_logout_before_consent_cannot_create_another_code(browser_flow):
    from oauth2_provider.models import Grant

    flow = browser_flow
    issued = flow.code()
    consent = flow.browser.get("/oauth/authorize/", issued.parameters)
    fields = {
        key: value
        for key, value in consent.context_data["form"].initial.items()
        if value is not None
    }
    fields["allow"] = "true"
    csrf = flow.browser.get("/api/auth-options").json()["csrf_token"]
    flow.native.logout(flow.browser.cookies["keeplane_session"].value)
    response = flow.browser.post(
        "/oauth/authorize/", urlencode(fields), content_type=FORM, HTTP_X_CSRFTOKEN=csrf
    )
    assert response.status_code == 302 and response["Location"].startswith(
        "/sign-in?return_to="
    )
    assert Grant.objects.count() == 1
    assert (
        flow.exchange(issued).status_code == 200
    )  # A previously approved CLI grant is independent.


def test_consent_csrf_and_cookie_only_token_request_do_not_weaken_browser_writes(
    browser_flow,
):
    flow = browser_flow
    issued = flow.code()
    consent = flow.browser.get("/oauth/authorize/", issued.parameters)
    fields = {
        key: value
        for key, value in consent.context_data["form"].initial.items()
        if value is not None
    }
    fields["allow"] = "true"
    assert (
        flow.browser.post(
            "/oauth/authorize/", urlencode(fields), content_type=FORM
        ).status_code
        == 403
    )
    assert (
        flow.browser.post(
            "/api/session", {"username": "first-admin"}, content_type="application/json"
        ).status_code
        == 403
    )
    assert (
        flow.browser.post(
            "/oauth/token/",
            urlencode(
                {"grant_type": "authorization_code", "client_id": "keeplane-cli"}
            ),
            content_type=FORM,
        ).status_code
        == 400
    )
    assert flow.exchange(issued).status_code == 200


@pytest.mark.parametrize(
    "change", ["redirect", "plain", "scope", "client", "duplicate"]
)
def test_authorization_refuses_unsafe_protocol_context_without_redirect(
    browser_flow, change
):
    flow = browser_flow
    issued = flow.code()
    parameters = dict(issued.parameters)
    if change == "redirect":
        parameters["redirect_uri"] = "https://foreign.invalid/callback"
    elif change == "plain":
        parameters["code_challenge_method"] = "plain"
    elif change == "scope":
        parameters["scope"] = "other"
    elif change == "client":
        parameters["client_id"] = "other-client"
    values = list(parameters.items()) + (
        [("state", "duplicate-state")] if change == "duplicate" else []
    )
    response = flow.browser.get("/oauth/authorize/?" + urlencode(values))
    assert response.status_code == 400 and "Location" not in response


def test_unknown_request_fields_cannot_choose_the_actor_or_scope(browser_flow):
    from oauth2_provider.models import Grant

    flow = browser_flow
    issued = flow.code(
        {
            "owner_id": "untrusted",
            "role": "admin",
            "resource": "https://foreign.invalid",
        }
    )
    grant = Grant.objects.get()
    assert (
        grant.user_id == flow.owner.pk
        and grant.scope == "runtime"
        and grant.resource == []
    )
    assert flow.exchange(issued).status_code == 200


def test_fixed_client_registration_is_idempotent_and_edits_are_not_silently_accepted(
    browser_flow,
):
    from django.core.management.base import CommandError
    from oauth2_provider.models import Application

    call_command("register_cli_client", verbosity=0)
    assert Application.objects.filter(client_id="keeplane-cli").count() == 1
    Application.objects.update(skip_authorization=True)
    with pytest.raises(CommandError):
        call_command("register_cli_client", verbosity=0)
    issued_parameters = {
        "client_id": "keeplane-cli",
        "response_type": "code",
        "scope": "runtime",
        "redirect_uri": "http://127.0.0.1:62431/callback",
        "state": "a" * 43,
        "code_challenge": "b" * 43,
        "code_challenge_method": "S256",
    }
    response = browser_flow.browser.get("/oauth/authorize/", issued_parameters)
    assert response.status_code == 400 and response.json() == {
        "error": "invalid_client"
    }


def test_trial_off_and_non_loopback_http_never_issue(browser_flow):
    flow = browser_flow
    issued = flow.code()
    for options in (
        {"CLI_OAUTH_ENABLED": False},
        {"PUBLIC_ORIGIN": "http://insecure.invalid"},
    ):
        with override_settings(**options):
            assert flow.exchange(issued).status_code in {403, 404, 503}
    assert flow.exchange(issued).status_code == 200


def test_binding_failure_rolls_back_tokens_and_keeps_code_retryable(
    browser_flow, monkeypatch
):
    from accounts import oauth_validator
    from django.db import DatabaseError
    from oauth2_provider.models import AccessToken, Grant, RefreshToken

    flow = browser_flow
    issued = flow.code()
    bind = oauth_validator.bind_issued_token

    def fail_refresh(kind, *args):
        if kind == "refresh":
            raise DatabaseError("synthetic confidential error")
        return bind(kind, *args)

    with monkeypatch.context() as patch:
        patch.setattr(oauth_validator, "bind_issued_token", fail_refresh)
        response = flow.exchange(issued)
    assert response.status_code == 503 and b"confidential" not in response.content
    assert not AccessToken.objects.exists() and not RefreshToken.objects.exists()
    assert (
        Grant.objects.count() == 1
        and CliCredentialBinding.objects.filter(kind="code").count() == 1
    )
    assert flow.exchange(issued).status_code == 200


def test_withdrawal_wins_before_owner_lock_even_with_unchanged_password_hash(
    browser_flow, monkeypatch
):
    from oauth2_provider.models import AccessToken

    flow = browser_flow
    issued = flow.code()
    original_hash = flow.owner.get_session_auth_hash()
    select = User.objects.select_for_update
    withdrawn = []

    def withdraw_then_lock(*args, **kwargs):
        if not withdrawn:
            withdrawn.append(True)
            revoke(flow.owner)
        return select(*args, **kwargs)

    monkeypatch.setattr(User.objects, "select_for_update", withdraw_then_lock)
    assert flow.exchange(issued).status_code == 400
    assert (
        flow.owner.get_session_auth_hash() == original_hash
        and not AccessToken.objects.exists()
    )


def test_first_admin_browser_sign_in_keeps_mandatory_audit(browser_flow):
    from audit.contracts import BREAK_GLASS_KIND
    from audit.models import AuditRecord

    flow = browser_flow
    flow.sign_in("first-admin", flow.domain.secret.read_text().strip())
    assert AuditRecord.objects.filter(kind=BREAK_GLASS_KIND).exists()
    value = flow.exchange(flow.code()).json()
    assert flow.identity.session(value["access_token"])["username"] == "first-admin"
