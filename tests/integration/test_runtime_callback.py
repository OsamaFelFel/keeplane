"""Both identities and current stored policy protect private HTTP decisions."""

import json
import secrets
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from accounts import authentication
from accounts.models import User
from data_classes.models import ProjectClass
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import Client, override_settings
from django.utils import timezone
from model_registry import runtime_callback
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy
from projects.models import Project
from projects.services import DjangoProjectStore


@pytest.fixture
def callback(domain_services, tmp_path, monkeypatch):
    stores, password = domain_services, "callback-test-password"
    actor = stores.identity.create_user(
        {"username": "callback-developer", "role": "developer", "password": password}
    )
    token = stores.identity.login(actor["username"], password)
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(actor["id"], project, "Callback")
    stores.classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project, data_class_id="confidential")
    resources = [
        {"id": name, "revision": 1} for name in ("private", "public", "outside")
    ]
    for name, classes in (("private", ["Confidential"]), ("public", ["Public"])):
        stores.catalog.approve(name, classes, fingerprint(name, resources))
    state = SimpleNamespace(status=200)
    gateway = SimpleNamespace(
        models=lambda: (state.status, {"data": [{"id": r["id"]} for r in resources]}),
        resources=lambda: (state.status, {"resources": resources}),
    )
    key, path = secrets.token_urlsafe(32), tmp_path / "gateway-key"
    path.write_text(key + "\n")
    path.chmod(0o600)
    monkeypatch.setattr(authentication, "IDENTITY", stores.identity)
    monkeypatch.setattr(runtime_callback, "IDENTITY", stores.identity)
    monkeypatch.setattr(
        runtime_callback, "model_policy", lambda: DjangoModelPolicy(gateway)
    )
    with override_settings(
        ALLOWED_HOSTS=["testserver"], RUNTIME_AUTHORIZER_KEY_FILE=str(path)
    ):
        yield SimpleNamespace(
            client=Client(enforce_csrf_checks=True),
            actor=actor,
            token=token,
            project=project,
            stores=stores,
            state=state,
            key=key,
            key_file=path,
            resources=resources,
            gateway=gateway,
        )


def send(callback, body=None, **headers):
    return callback.client.post(
        "/internal/runtime/authorize",
        data=json.dumps(
            body or {"project_id": callback.project, "model_id": "private"}
        ),
        content_type="application/json",
        **{
            "HTTP_AUTHORIZATION": "Bearer " + callback.token,
            "HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": callback.key,
            **headers,
        },
    )


def test_result_contains_only_canonical_actor_project_model(callback):
    response = send(
        callback, {"project_id": uuid.UUID(callback.project).hex, "model_id": "private"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "actor_id": callback.actor["id"],
        "project_id": callback.project,
        "model_id": "private",
    }
    assert "no-store" in response["Cache-Control"]
    assert (
        callback.token not in response.content.decode()
        and callback.key not in response.content.decode()
    )


@pytest.mark.parametrize("key", ["", "incorrect" * 8, "é" * 32, "a" * 257])
def test_workload_identity_is_required_and_never_reflected(callback, key):
    response = send(callback, HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=key)
    assert response.status_code == 403
    assert response.json() == {"error": "Gateway credential is invalid"}
    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize(
    "configuration", ["missing", "relative", "invalid", "oversized"]
)
def test_unavailable_key_configuration_denies(callback, configuration):
    if configuration == "missing":
        callback.key_file.unlink()
    elif configuration == "relative":
        with override_settings(RUNTIME_AUTHORIZER_KEY_FILE="gateway-key"):
            assert send(callback).status_code == 503
        return
    else:
        callback.key_file.write_text(
            "bad key" if configuration == "invalid" else "a" * 259
        )
    response = send(callback)
    assert response.status_code == 503
    assert str(callback.key_file) not in response.content.decode()


def test_key_rotation_is_immediate(callback):
    assert send(callback).status_code == 200
    new_key = secrets.token_urlsafe(32)
    replacement = callback.key_file.with_suffix(".new")
    replacement.write_text(new_key)
    replacement.replace(callback.key_file)
    assert send(callback).status_code == 403
    assert send(callback, HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=new_key).status_code == 200


@pytest.mark.parametrize(
    "withdrawal", ["cookie-only", "expired", "revoked", "disabled"]
)
def test_gateway_key_cannot_replace_current_developer_identity(callback, withdrawal):
    if withdrawal == "expired":
        Session.objects.filter(pk=callback.token).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
    elif withdrawal == "revoked":
        callback.stores.identity.logout(callback.token)
    elif withdrawal == "disabled":
        User.objects.filter(pk=callback.actor["id"]).update(is_active=False)
    else:
        callback.client.cookies["keeplane_session"] = callback.token
    response = send(
        callback,
        HTTP_AUTHORIZATION=""
        if withdrawal == "cookie-only"
        else "Bearer " + callback.token,
    )
    assert response.status_code == 401 and response["WWW-Authenticate"] == "Bearer"


def test_unknown_or_denied_project_has_no_decision_or_registration(
    callback, monkeypatch
):
    assert (
        send(
            callback, {"project_id": str(uuid.uuid4()), "model_id": "private"}
        ).status_code
        == 403
    )
    monkeypatch.setattr(
        runtime_callback, "organization_project_access", lambda *args: None
    )
    assert send(callback).status_code == 403
    assert Project.objects.count() == 1


def test_admin_cannot_bypass_class_setup_or_withdrawal(callback):
    User.objects.filter(pk=callback.actor["id"]).update(role="admin")
    for name in ("public", "outside"):
        assert (
            send(
                callback, {"project_id": callback.project, "model_id": name}
            ).status_code
            == 403
        )
    assert send(callback).status_code == 200
    callback.stores.catalog.remove("private")
    assert send(callback).status_code == 403


def test_gateway_and_storage_failure_fail_closed(callback, monkeypatch):
    callback.state.status = 503
    assert send(callback).status_code == 503

    def unavailable(*args, **kwargs):
        raise DatabaseError("unavailable test database")

    monkeypatch.setattr(Project.objects, "filter", unavailable)
    assert send(callback).status_code == 503


@pytest.mark.parametrize(
    "change",
    [
        {"prompt": "do not accept prompts"},
        {"actor_id": "other"},
        {"data_class": "Public"},
        {"model_id": ["private"]},
    ],
)
def test_body_cannot_claim_authority_or_carry_prompt(callback, change):
    response = send(
        callback, {"project_id": callback.project, "model_id": "private", **change}
    )
    assert response.status_code == 400
    assert response.json() == {"error": "Send only a project ID and model ID"}


def test_bounded_and_malformed_metadata_is_rejected(callback):
    assert (
        send(
            callback, {"project_id": callback.project, "model_id": "x" * 4096}
        ).status_code
        == 413
    )
    headers = {
        "HTTP_AUTHORIZATION": "Bearer " + callback.token,
        "HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": callback.key,
    }
    for body in ("{", "[" * 2000, "[]", "{}"):
        assert (
            callback.client.post(
                "/internal/runtime/authorize",
                data=body,
                content_type="application/json",
                **headers,
            ).status_code
            == 400
        )
    assert (
        callback.client.post(
            "/internal/runtime/authorize",
            data="{}",
            content_type="text/plain",
            **headers,
        ).status_code
        == 415
    )


def test_final_decision_requires_current_managed_shared_key(
    callback, tmp_path, monkeypatch
):
    root = tmp_path / "managed-keys"
    root.mkdir(mode=0o700)
    path = root / ("key-" + uuid.uuid4().hex)
    path.write_text("synthetic-shared-provider-key")
    path.chmod(0o600)
    callback.resources[0]["value"] = {"auth": {"key": {"value": {"file": str(path)}}}}
    callback.stores.catalog.approve(
        "private",
        ["Confidential"],
        fingerprint("private", callback.resources),
        key_choice="shared",
    )
    monkeypatch.setenv("PROVIDER_KEY_DIR", str(root))
    monkeypatch.setattr(runtime_callback, "MODEL_GATEWAY", callback.gateway)
    assert send(callback).status_code == 200
    path.unlink()
    response = send(callback)
    assert response.status_code == 503
    assert response.json() == {"error": "Gateway authorization is unavailable"}
    assert str(path) not in response.content.decode()
    # Catalog eligibility remains setup/class policy, not a key-health claim.
    assert DjangoModelPolicy(callback.gateway).eligible_model_ids(callback.project) == {
        "private"
    }


def test_shared_key_definition_change_is_unavailable(callback, tmp_path, monkeypatch):
    callback.stores.catalog.approve(
        "private",
        ["Confidential"],
        fingerprint("private", callback.resources),
        key_choice="shared",
    )
    monkeypatch.setattr(runtime_callback, "MODEL_GATEWAY", callback.gateway)
    callback.resources[0]["revision"] += 1
    # A concurrent definition change cannot make the final shared-key check trust it.
    from model_registry.policy import ModelPolicyUnavailable
    from model_registry.provider_keys import DjangoSharedKeyAvailability

    with pytest.raises(ModelPolicyUnavailable):
        DjangoSharedKeyAvailability(callback.gateway, str(tmp_path)).require_available(
            "private"
        )
