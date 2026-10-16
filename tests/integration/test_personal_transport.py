"""Private HTTP transport against actual account, policy and key-file state."""

import secrets
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from accounts.models import User
from data_classes.models import ProjectClass
from django.db import DatabaseError
from django.test import Client, override_settings
from model_registry import personal_transport
from model_registry.models import ModelApproval

from tests.integration import test_personal_dispatch as dispatch_cases

pytestmark = pytest.mark.django_db(transaction=True)
key_owner = dispatch_cases.key_owner
dispatch = dispatch_cases.dispatch
KEY, NEXT = dispatch_cases.KEY, dispatch_cases.NEXT
PATH = "/internal/runtime/provider-token"


@pytest.fixture
def transport(dispatch, tmp_path, monkeypatch):
    key_file = tmp_path / "callback-key"
    key = secrets.token_urlsafe(32)
    key_file.write_text(key)
    key_file.chmod(0o600)
    monkeypatch.setattr(personal_transport, "IDENTITY", dispatch.identity)
    monkeypatch.setattr(personal_transport, "MODEL_GATEWAY", dispatch.service.gateway)
    monkeypatch.setattr(
        personal_transport,
        "model_policy",
        lambda: dispatch.service.authorization.model_policy,
    )
    monkeypatch.setenv("PROVIDER_KEY_DIR", str(dispatch.owned.root))
    with override_settings(
        ALLOWED_HOSTS=["testserver"], RUNTIME_AUTHORIZER_KEY_FILE=str(key_file)
    ):
        yield SimpleNamespace(
            client=Client(enforce_csrf_checks=True),
            key=key,
            key_file=key_file,
            dispatch=dispatch,
        )


def fields(transport):
    return {
        "grant_type": personal_transport.EXCHANGE_TYPE,
        "subject_token_type": personal_transport.ACCESS_TYPE,
        "subject_token": transport.dispatch.tokens[0],
        "project_id": transport.dispatch.project,
        "model_id": "model",
        "definition_fingerprint": transport.dispatch.owned.digest,
    }


def send(transport, body=None, *, key=None, content_type=None, **headers):
    return transport.client.post(
        PATH,
        data=urlencode(fields(transport) if body is None else body),
        content_type=content_type or "application/x-www-form-urlencoded",
        **{
            "HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": transport.key if key is None else key,
            **headers,
        },
    )


def private_error(transport, response):
    text = response.content.decode()
    assert all(
        value not in text
        for value in (
            KEY,
            NEXT,
            transport.key,
            *transport.dispatch.tokens,
            str(transport.dispatch.owned.root),
        )
    )
    assert "no-store" in response["Cache-Control"]


def test_private_adapter_returns_only_selected_owner_key_and_never_caches(transport):
    response = send(transport)
    assert response.status_code == 200
    assert response.json() == {
        "access_token": KEY,
        "token_type": "Bearer",
        "issued_token_type": personal_transport.ACCESS_TYPE,
    }
    assert "no-store" in response["Cache-Control"] and response["Pragma"] == "no-cache"
    assert transport.dispatch.tokens[0] not in response.content.decode()
    transport.dispatch.owned.a.put("model", NEXT)
    assert send(transport).json()["access_token"] == NEXT
    transport.dispatch.owned.a.remove("model")
    response = send(transport)
    assert response.status_code == 503
    private_error(transport, response)


def test_subject_selects_owner_independently_of_browser_and_header_claims(transport):
    transport.dispatch.owned.b.put("model", NEXT)
    body = fields(transport)
    body["subject_token"] = transport.dispatch.tokens[1]
    transport.client.cookies["keeplane_session"] = transport.dispatch.tokens[0]
    response = send(
        transport,
        body,
        HTTP_AUTHORIZATION="Bearer " + transport.dispatch.tokens[0],
        HTTP_X_KEEPLANE_USER_ID=transport.dispatch.owned.a.owner_id,
        HTTP_X_KEEPLANE_PROJECT_CLASS="Public",
    )
    assert response.status_code == 200 and response.json()["access_token"] == NEXT
    assert send(transport).json()["access_token"] == KEY


@pytest.mark.parametrize("key", ["", "incorrect" * 8, "é" * 32, "a" * 257])
def test_public_credentials_cannot_replace_private_callback_identity(transport, key):
    transport.client.cookies["keeplane_session"] = transport.dispatch.tokens[0]
    response = send(
        transport,
        key=key,
        HTTP_AUTHORIZATION="Bearer " + transport.dispatch.tokens[0],
    )
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Keeplane-Gateway"
    assert not transport.dispatch.reads
    private_error(transport, response)


def test_callback_rotation_withdraws_old_private_credential(transport):
    assert send(transport).status_code == 200
    replacement = secrets.token_urlsafe(32)
    transport.key_file.write_text(replacement)
    assert send(transport).status_code == 401
    assert send(transport, key=replacement).status_code == 200
    transport.key_file.unlink()
    response = send(transport, key=replacement)
    assert response.status_code == 503
    private_error(transport, response)


@pytest.mark.parametrize(
    "change",
    [
        {"grant_type": "client_credentials"},
        {"subject_token_type": "urn:other"},
        {"requested_token_type": "urn:other"},
        {"subject_token": ""},
        {"subject_token": "x" * 201},
        {"project_id": ""},
        {"model_id": ""},
        {"definition_fingerprint": "A" * 64},
        {"actor_token": "someone-else"},
        {"prompt": "Do not accept prompts"},
        {"data_class": "Public"},
    ],
)
def test_only_bounded_metadata_is_accepted_before_secret_reads(transport, change):
    response = send(transport, {**fields(transport), **change})
    assert response.status_code == 400 and response.json() == {
        "error": "invalid_request"
    }
    assert not transport.dispatch.reads
    private_error(transport, response)


@pytest.mark.parametrize("raw", ["broken", "x=" + "x" * 4096, "subject_token=%FF"])
def test_malformed_and_oversized_form_is_denied(transport, raw):
    response = transport.client.post(
        PATH,
        data=raw,
        content_type="application/x-www-form-urlencoded",
        HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=transport.key,
    )
    assert response.status_code == 400 and not transport.dispatch.reads
    private_error(transport, response)


def test_duplicate_fields_and_non_form_content_are_denied(transport):
    body = list(fields(transport).items()) + [("model_id", "other")]
    response = send(transport, body)
    assert response.status_code == 400 and not transport.dispatch.reads
    assert send(transport, content_type="application/json").status_code == 400
    body = {**fields(transport), "requested_token_type": personal_transport.ACCESS_TYPE}
    assert send(transport, body).status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        "logout",
        "disabled",
        "class",
        "project",
        "definition",
        "key-choice",
        "key-missing",
    ],
)
def test_current_policy_and_key_state_withdraw_each_handoff(
    transport, change, monkeypatch
):
    owned = transport.dispatch.owned
    if change == "logout":
        transport.dispatch.identity.logout(transport.dispatch.tokens[0])
    elif change == "disabled":
        User.objects.filter(pk=owned.a.owner_id).update(is_active=False)
    elif change == "class":
        ProjectClass.objects.update(data_class_id="public")
    elif change == "project":
        monkeypatch.setattr(
            personal_transport, "organization_project_access", lambda *args: False
        )
    elif change == "definition":
        owned.resource["revision"] += 1
    elif change == "key-choice":
        ModelApproval.objects.update(key_choice="shared")
    else:
        owned.a.remove("model")
    response = send(transport)
    assert response.status_code in (400, 503) and not transport.dispatch.reads
    private_error(transport, response)


def test_database_failure_does_not_disclose_credentials(transport, monkeypatch):
    def unavailable(*args, **kwargs):
        raise DatabaseError(KEY)

    monkeypatch.setattr(
        personal_transport.DjangoPersonalDispatch, "resolve", unavailable
    )
    response = send(transport)
    assert response.status_code == 503
    private_error(transport, response)
