"""Only both current private credentials admit raw operator model validation."""

import json
import secrets
from types import SimpleNamespace

import pytest
from django.test import Client, override_settings
from model_registry import runtime_callback
from model_registry.models import ModelApproval

URL = "/internal/runtime/installed/operator-validation"
pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(tmp_path, monkeypatch):
    f = SimpleNamespace(client=Client(enforce_csrf_checks=True), contacts=[])
    f.callback_key, f.runtime_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    f.callback_file, f.runtime_file = tmp_path / "callback", tmp_path / "runtime"
    f.callback_file.write_text(f.callback_key)
    f.runtime_file.write_text(f.runtime_key)
    monkeypatch.setenv("GATEWAY_RUNTIME_KEY_FILE", str(f.runtime_file))
    monkeypatch.setenv("GATEWAY_MODE", "managed")

    def unexpected(*args, **kwargs):
        f.contacts.append(True)
        raise AssertionError("Operator callback must not contact identity or gateway")

    monkeypatch.setattr(runtime_callback, "authorized_model", unexpected)
    monkeypatch.setattr(runtime_callback.DjangoPersonalDispatch, "resolve", unexpected)
    monkeypatch.setattr(
        runtime_callback, "MODEL_GATEWAY", SimpleNamespace(request=unexpected)
    )
    with override_settings(
        ALLOWED_HOSTS=["testserver"],
        RUNTIME_AUTHORIZER_KEY_FILE=str(f.callback_file),
        RUNTIME_GUARD_MANIFEST_FILE=str(tmp_path / "absent-manifest"),
    ):
        yield f
    assert not f.contacts


def send(f, *, body=None, raw=None, content_type="application/json", **headers):
    return f.client.post(
        URL,
        data=raw
        if raw is not None
        else json.dumps(
            {"model_id": "private", "definition_fingerprint": "a" * 64}
            if body is None
            else body
        ),
        content_type=content_type,
        **{
            "HTTP_AUTHORIZATION": "Bearer " + f.runtime_key,
            "HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": f.callback_key,
            "HTTP_X_KEEPLANE_INSTALLED_RUNTIME": "operator",
            **headers,
        },
    )


def test_private_validation_can_run_before_enrollment_without_claiming_user_access(
    operator,
):
    response = send(operator)
    assert response.status_code == 200 and response.json() == {"allowed": True}
    assert "no-store" in response["Cache-Control"]
    assert all(
        secret not in response.content.decode()
        for secret in (
            operator.callback_key,
            operator.runtime_key,
            str(operator.runtime_file),
            "a" * 64,
        )
    )


@pytest.mark.parametrize(
    "choice,status", [("none", 200), ("shared", 200), ("personal", 403)]
)
def test_raw_personal_denies_without_resolving_keys_but_other_validation_remains(
    operator, choice, status
):
    ModelApproval.objects.create(
        model_id="private", key_choice=choice, gateway_fingerprint="a" * 64
    )
    assert send(operator).status_code == status and not operator.contacts


@pytest.mark.parametrize("marker", ["", "1", "forged", "operator,1", "Operator"])
def test_marker_must_be_exact_operator_marker(operator, marker):
    response = send(operator, HTTP_X_KEEPLANE_INSTALLED_RUNTIME=marker)
    assert response.status_code == 403
    assert response.json() == {"error": "Operator validation is unavailable"}


@pytest.mark.parametrize(
    "header,value",
    [
        ("HTTP_AUTHORIZATION", ""),
        ("HTTP_AUTHORIZATION", "Bearer " + "incorrect" * 8),
        ("HTTP_AUTHORIZATION", "Bearer " + "é" * 32),
        ("HTTP_AUTHORIZATION", "Bearer " + "a" * 257),
        ("HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL", ""),
        ("HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL", "incorrect" * 8),
        ("HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL", "é" * 32),
    ],
)
def test_each_private_credential_is_required_and_not_reflected(operator, header, value):
    response = send(operator, **{header: value})
    assert response.status_code == 403
    assert value not in response.content.decode() if value else True


def test_current_developer_bearer_cannot_select_operator_validation(
    operator, domain_services
):
    actor = domain_services.identity.create_user(
        {
            "username": "operator-callback-test",
            "role": "developer",
            "password": "test-password-123",
        }
    )
    token = domain_services.identity.login(actor["username"], "test-password-123")
    assert send(operator, HTTP_AUTHORIZATION="Bearer " + token).status_code == 403


def test_browser_cookie_cannot_replace_the_private_runtime_bearer(operator):
    operator.client.cookies["keeplane_session"] = operator.runtime_key
    assert send(operator, HTTP_AUTHORIZATION="").status_code == 403


@pytest.mark.parametrize("which", ["runtime", "callback"])
def test_replacing_either_private_file_immediately_withdraws_its_old_value(
    operator, which
):
    assert send(operator).status_code == 200
    replacement = getattr(operator, which + "_file").with_suffix(".new")
    key = secrets.token_urlsafe(32)
    replacement.write_text(key)
    replacement.replace(getattr(operator, which + "_file"))
    assert send(operator).status_code == 403
    header = (
        {"HTTP_AUTHORIZATION": "Bearer " + key}
        if which == "runtime"
        else {"HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": key}
    )
    assert send(operator, **header).status_code == 200


@pytest.mark.parametrize(
    "configuration", ["missing", "relative", "invalid", "oversized"]
)
def test_unavailable_server_runtime_key_denies(operator, monkeypatch, configuration):
    if configuration == "missing":
        operator.runtime_file.unlink()
    elif configuration == "relative":
        monkeypatch.setenv("GATEWAY_RUNTIME_KEY_FILE", "runtime")
    else:
        operator.runtime_file.write_text(
            "invalid key" if configuration == "invalid" else "a" * 259
        )
    response = send(operator)
    assert response.status_code == 503
    assert str(operator.runtime_file) not in response.content.decode()


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        {
            "model_id": "private",
            "definition_fingerprint": "a" * 64,
            "project_id": "forged",
        },
        {
            "model_id": "private",
            "definition_fingerprint": "a" * 64,
            "actor_id": "forged",
        },
        {
            "model_id": "private",
            "definition_fingerprint": "a" * 64,
            "prompt": "unexpected",
        },
        {"model_id": ["private"], "definition_fingerprint": "a" * 64},
        {"model_id": "private", "definition_fingerprint": "A" * 64},
    ],
)
def test_body_has_only_bounded_constant_model_metadata(operator, body):
    assert send(operator, body=body).status_code == 400


@pytest.mark.parametrize(
    "raw,status",
    [
        ('{"model_id":"private","model_id":"other"}', 400),
        ("[" * 2000, 400),
        ("x" * 4097, 413),
    ],
    ids=["duplicate", "malformed", "oversized"],
)
def test_duplicate_malformed_and_oversized_json_denies(operator, raw, status):
    assert send(operator, raw=raw).status_code == status


def test_other_methods_content_types_and_existing_mode_are_unavailable(
    operator, monkeypatch
):
    assert (
        operator.client.get(
            URL,
            HTTP_AUTHORIZATION="Bearer " + operator.runtime_key,
            HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=operator.callback_key,
            HTTP_X_KEEPLANE_INSTALLED_RUNTIME="operator",
        ).status_code
        == 405
    )
    assert send(operator, content_type="text/plain").status_code == 415
    monkeypatch.setenv("GATEWAY_MODE", "existing")
    assert send(operator).status_code == 403
