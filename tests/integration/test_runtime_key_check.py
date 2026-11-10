"""The key-only check a customer-run gateway calls for Keeplane's own setup probe.

Cases RKC-01 to RKC-09 in tests/integration/runtime-key-check-cases.md.
"""

import secrets
from datetime import timedelta
from importlib.util import find_spec
from types import SimpleNamespace

import pytest
from django.test import Client, override_settings
from model_registry import runtime_callback

URL = "/internal/runtime/authorize/runtime-key"
pytestmark = pytest.mark.django_db


@pytest.fixture
def check(tmp_path, monkeypatch):
    f = SimpleNamespace(client=Client(enforce_csrf_checks=True), contacts=[])
    f.callback_key, f.runtime_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    f.callback_file, f.runtime_file = tmp_path / "callback", tmp_path / "runtime"
    f.callback_file.write_text(f.callback_key + "\n")
    f.runtime_file.write_text(f.runtime_key + "\n")
    monkeypatch.setenv("GATEWAY_RUNTIME_KEY_FILE", str(f.runtime_file))
    monkeypatch.setenv("GATEWAY_MODE", "existing")

    def unexpected(*args, **kwargs):
        f.contacts.append(True)
        raise AssertionError("The key-only check reads no developer policy")

    monkeypatch.setattr(runtime_callback, "authorized_model", unexpected)
    monkeypatch.setattr(runtime_callback, "record_sent_request", unexpected)
    monkeypatch.setattr(
        runtime_callback, "MODEL_GATEWAY", SimpleNamespace(request=unexpected)
    )
    with override_settings(
        ALLOWED_HOSTS=["testserver"], RUNTIME_AUTHORIZER_KEY_FILE=str(f.callback_file)
    ):
        yield f
    assert not f.contacts


def send(f, **headers):
    return f.client.post(
        URL,
        data="{}",
        content_type="application/json",
        **{
            "HTTP_AUTHORIZATION": "Bearer " + f.runtime_key,
            "HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": f.callback_key,
            **headers,
        },
    )


def refused(response):
    return response.status_code == 403 and response.json() == {
        "error": "Only Keeplane's runtime key is accepted"
    }


def developer_token(domain_services):
    actor = domain_services.identity.create_user(
        {
            "username": "key-check-developer",
            "role": "developer",
            "password": "key-check-password-1",
        }
    )
    return actor, domain_services.identity.login(
        actor["username"], "key-check-password-1"
    )


def test_rkc_01_the_runtime_key_and_gateway_credential_are_admitted(check):
    response = send(check)
    assert response.status_code == 200 and response.json() == {"allowed": True}
    assert "no-store" in response["Cache-Control"]
    body = response.content.decode()
    assert all(
        secret not in body
        for secret in (check.callback_key, check.runtime_key, str(check.runtime_file))
    )
    # The check reads no body: whatever the gateway sends, the keys decide.
    for raw, content_type in (("", "text/plain"), ('{"model_id": 1}', "text/plain")):
        answer = check.client.post(
            URL,
            data=raw,
            content_type=content_type,
            HTTP_AUTHORIZATION="Bearer " + check.runtime_key,
            HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=check.callback_key,
        )
        assert answer.status_code == 200


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Bearer",
        "Bearer " + "incorrect" * 8,
        "Basic " + "a" * 43,
        "Bearer " + "é" * 32,
        "Bearer " + "a" * 257,
        "Bearer short",
    ],
    ids=["none", "empty", "wrong", "basic", "non-ascii", "too-long", "too-short"],
)
def test_rkc_02_a_missing_or_wrong_bearer_is_refused(check, value):
    response = send(check, HTTP_AUTHORIZATION=value)
    assert refused(response)
    if value:
        assert value.split()[-1] not in response.content.decode()


def test_rkc_02_the_runtime_key_with_a_different_case_or_suffix_is_refused(check):
    for value in (check.runtime_key.swapcase(), check.runtime_key + "x"):
        assert refused(send(check, HTTP_AUTHORIZATION="Bearer " + value))


@pytest.mark.parametrize("value", ["", "incorrect" * 8, "é" * 32, None])
def test_rkc_03_the_gateway_credential_is_required_too(check, value):
    headers = {"HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": value}
    if value is None:
        # The two keys swapped over.
        headers = {
            "HTTP_AUTHORIZATION": "Bearer " + check.callback_key,
            "HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": check.runtime_key,
        }
    assert refused(send(check, **headers))


def test_rkc_04_a_current_developer_session_is_refused(check, domain_services):
    _, token = developer_token(domain_services)
    assert refused(send(check, HTTP_AUTHORIZATION="Bearer " + token))


def test_rkc_05_a_signed_in_browser_cookie_is_refused(check, domain_services):
    _, token = developer_token(domain_services)
    admin = domain_services.identity.login("first-admin", "first-test-password-123")
    for cookie in (token, admin, check.runtime_key):
        check.client.cookies["keeplane_session"] = cookie
        answer = send(check, HTTP_AUTHORIZATION="")
        # Refused by the key check itself, not by a CSRF failure.
        assert refused(answer), cookie
    # A cookie never adds to a wrong bearer either.
    assert refused(send(check, HTTP_AUTHORIZATION="Bearer " + admin))


@pytest.mark.optional
@pytest.mark.live
@pytest.mark.skipif(
    not find_spec("oauth2_provider"), reason="Install the pinned CLI sign-in packages"
)
def test_rkc_06_a_cli_sign_in_token_is_refused(check, domain_services):
    from accounts.cli_credentials import access_token, bind_issued_token
    from accounts.models import CliCredentialBinding, User
    from django.db import transaction
    from django.utils import timezone
    from oauth2_provider.models import AccessToken, Application, set_token_value

    actor, _ = developer_token(domain_services)
    owner = User.objects.get(pk=actor["id"])
    app = Application.objects.create(
        client_id="keeplane-cli",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="http://127.0.0.1/callback",
        name="Keeplane CLI",
    )
    raw = access_token()
    with transaction.atomic():
        token = AccessToken(
            user=owner,
            application=app,
            scope="runtime",
            expires=timezone.now() + timedelta(hours=1),
        )
        set_token_value(token, raw)
        token.save()
        bind_issued_token(
            CliCredentialBinding.Kind.ACCESS,
            raw,
            owner.pk,
            owner.get_session_auth_hash(),
        )
    with override_settings(CLI_OAUTH_ENABLED=True):
        assert refused(send(check, HTTP_AUTHORIZATION="Bearer " + raw))


@pytest.mark.parametrize("mode", ["managed", None, "Existing", "other"])
def test_rkc_07_only_an_existing_gateway_install_has_the_check(
    check, monkeypatch, mode
):
    if mode is None:
        monkeypatch.delenv("GATEWAY_MODE")
    else:
        monkeypatch.setenv("GATEWAY_MODE", mode)
    response = send(check)
    assert response.status_code == 403
    assert response.json() == {
        "error": "Managed gateways use the installed runtime checks"
    }
    # Refused before any key is read: a missing key file changes nothing.
    check.runtime_file.unlink()
    assert send(check).status_code == 403


@pytest.mark.parametrize("which", ["runtime", "callback"])
def test_rkc_08_a_replaced_key_withdraws_the_old_one_at_once(check, which):
    assert send(check).status_code == 200
    key = secrets.token_urlsafe(32)
    replacement = getattr(check, which + "_file").with_suffix(".new")
    replacement.write_text(key)
    replacement.replace(getattr(check, which + "_file"))
    assert refused(send(check))
    header = (
        {"HTTP_AUTHORIZATION": "Bearer " + key}
        if which == "runtime"
        else {"HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": key}
    )
    assert send(check, **header).status_code == 200


@pytest.mark.parametrize(
    "configuration",
    ["missing", "unset", "relative", "invalid", "oversized", "callback-missing"],
)
def test_rkc_09_an_unreadable_key_fails_closed(check, monkeypatch, configuration):
    if configuration == "missing":
        check.runtime_file.unlink()
    elif configuration == "unset":
        monkeypatch.delenv("GATEWAY_RUNTIME_KEY_FILE")
    elif configuration == "relative":
        monkeypatch.setenv("GATEWAY_RUNTIME_KEY_FILE", "runtime")
    elif configuration == "callback-missing":
        check.callback_file.unlink()
    else:
        check.runtime_file.write_text(
            "invalid key" if configuration == "invalid" else "a" * 259
        )
    response = send(check)
    assert response.status_code == 503
    assert response.json() == {"error": "Gateway authorization is unavailable"}
    assert str(check.runtime_file) not in response.content.decode()


def test_rkc_09_other_methods_are_refused(check):
    for method in ("get", "put", "delete"):
        answer = getattr(check.client, method)(
            URL,
            HTTP_AUTHORIZATION="Bearer " + check.runtime_key,
            HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=check.callback_key,
        )
        assert answer.status_code == 405, method
    assert refused(check.client.get(URL))
