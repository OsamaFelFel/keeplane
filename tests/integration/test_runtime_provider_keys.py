"""Owner-only HTTP admission with real sessions, bound storage and mock provider."""

from json import scanner
from types import SimpleNamespace

import pytest
from accounts import authentication
from accounts.models import User
from django.contrib.sessions.models import Session
from django.db import DatabaseError, connection, transaction
from django.test import Client, override_settings
from django.utils import timezone
from model_registry import runtime_keys
from model_registry.fingerprints import fingerprint
from model_registry.key_validation import DjangoProviderKeyValidator
from model_registry.models import DeveloperProviderKey, ModelApproval

from tests.integration.test_provider_key_validation import KEY, setup
from tests.integration.test_provider_key_validation import provider as provider

pytestmark = pytest.mark.django_db(transaction=True)
PATH = "/api/runtime/provider-keys"


@pytest.fixture(autouse=True)
def fixture_password_hashes():
    with override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
    ):
        yield


@pytest.fixture
def api(domain_services, provider, tmp_path, monkeypatch):
    _, gateway = setup(provider)
    identity, password = domain_services.identity, "runtime-key-account-password"
    tokens = []
    for name, role in (("key-alice", "developer"), ("key-bob", "admin")):
        identity.create_user({"username": name, "password": password, "role": role})
        tokens.append(identity.login(name, password))
    monkeypatch.setattr(authentication, "IDENTITY", identity)
    monkeypatch.setattr(runtime_keys, "MODEL_GATEWAY", gateway)
    monkeypatch.setattr(
        runtime_keys,
        "DjangoProviderKeyValidator",
        lambda current: DjangoProviderKeyValidator(current, allow_loopback_http=True),
    )
    monkeypatch.setattr("integrations.gateway.keys.os.fchown", lambda *a: None)
    root = tmp_path / "keys"
    monkeypatch.setenv("PROVIDER_KEY_DIR", str(root))
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        yield SimpleNamespace(
            client=Client(enforce_csrf_checks=True),
            tokens=tokens,
            identity=identity,
            provider=provider,
            gateway=gateway,
            root=root,
        )


def send(api, method, *, actor=0, body=None, token=None, path=PATH):
    if method == "get":
        path += "?model_id=model"
    return getattr(api.client, method)(
        path,
        data={}
        if method == "get"
        else body
        if body is not None
        else {"model_id": "model"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + (token or api.tokens[actor]),
    )


def put(api, **kwargs):
    return send(api, "put", body={"model_id": "model", "key": KEY}, **kwargs)


def safe(response, status="added"):
    assert response.status_code == 200
    assert response.json() == {
        "model_id": "model",
        "status": status,
        "cleanup_pending": False,
    }
    assert "no-store" in response["Cache-Control"]
    assert KEY.encode() not in response.content


def test_two_owners_add_replace_status_and_remove_are_isolated(api):
    safe(send(api, "get"), "missing")
    safe(put(api))
    safe(send(api, "get", actor=1), "missing")
    safe(send(api, "put", actor=1, body={"model_id": "model", "key": KEY + "-bob"}))
    safe(send(api, "put", body={"model_id": "model", "key": KEY + "-replacement"}))
    safe(send(api, "get"))
    assert len(api.provider["calls"]) == 3
    assert DeveloperProviderKey.objects.count() == 2
    assert all(
        row.validation_fingerprint == fingerprint("model", [api.gateway.resource])
        for row in DeveloperProviderKey.objects.all()
    )
    safe(send(api, "delete"), "missing")
    safe(send(api, "get", actor=1))
    assert [path.read_text() for path in api.root.iterdir()] == [KEY + "-bob"]
    safe(send(api, "delete"), "missing")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_cookie_and_invalid_or_expired_bearer_cannot_manage_keys(api, method):
    api.client.cookies["keeplane_session"] = api.tokens[0]
    body = (
        {"model_id": "model", "key": KEY} if method == "put" else {"model_id": "model"}
    )
    response = getattr(api.client, method)(
        PATH + ("?model_id=model" if method == "get" else ""),
        data=body,
        content_type="application/json",
    )
    assert response.status_code == 401
    assert send(api, method, body=body, token="invalid").status_code == 401
    Session.objects.filter(session_key=api.tokens[0]).update(expire_date=timezone.now())
    assert send(api, method, body=body).status_code == 401
    assert not api.provider["calls"] and not DeveloperProviderKey.objects.exists()


@pytest.mark.parametrize("withdrawal", ["logout", "password", "disabled", "removed"])
def test_cached_request_rechecks_withdrawal_before_provider_contact(
    api, monkeypatch, withdrawal
):
    original = runtime_keys.key_store

    def withdraw_then_store(request, model_id):
        # DRF already authenticated. The withdrawal completes before key storage
        # takes its owner lock; cached request.user must not authorize a provider call.
        if withdrawal == "logout":
            api.identity.logout(request.auth)
        elif withdrawal == "removed":
            api.identity.delete_user(str(request.user.pk))
        else:
            with transaction.atomic():
                owner = User.objects.select_for_update().get(pk=request.user.pk)
                if withdrawal == "password":
                    owner.set_password("changed-runtime-key-password")
                    owner.save(update_fields=["password"])
                else:
                    owner.is_active = False
                    owner.save(update_fields=["is_active"])
        return original(request, model_id)

    monkeypatch.setattr(runtime_keys, "key_store", withdraw_then_store)
    response = put(api)
    assert response.status_code == 401
    assert not api.provider["calls"] and not DeveloperProviderKey.objects.exists()
    assert not api.root.exists()


@pytest.mark.parametrize("extra", ["owner_id", "filename", "fingerprint", "project_id"])
def test_client_claims_are_refused_without_provider_contact(api, extra):
    response = send(api, "put", body={"model_id": "model", "key": KEY, extra: "forged"})
    assert response.status_code == 400
    assert not api.provider["calls"] and not DeveloperProviderKey.objects.exists()


@pytest.mark.parametrize(
    "key", ["short", "x" * 513, "x" * 12 + "\n", "with spaces here", "非" * 12]
)
def test_invalid_key_and_bounded_exact_json_never_contact_provider(api, key):
    assert send(api, "put", body={"model_id": "model", "key": key}).status_code == 400
    assert not api.provider["calls"]


@pytest.mark.parametrize(
    "raw,status,kind",
    [
        ('{"model_id":"model","key":"one","key":"two"}', 400, "application/json"),
        ('{"model_id":"model","key":', 400, "application/json"),
        ("x" * 4097, 413, "application/json"),
        ("model_id=model&key=synthetic", 415, "application/x-www-form-urlencoded"),
    ],
)
def test_malformed_duplicate_large_or_non_json_body_is_generic(api, raw, status, kind):
    response = api.client.put(
        PATH, raw, content_type=kind, HTTP_AUTHORIZATION="Bearer " + api.tokens[0]
    )
    assert response.status_code == status
    assert raw.encode() not in response.content
    assert not api.provider["calls"]


def test_injected_json_recursion_failure_is_refused_before_key_or_provider_contact(
    api, monkeypatch
):
    # Fault injection selects the stdlib Python scanner to exercise recursion
    # failure; this body need not exceed the native C decoder's depth limit.
    monkeypatch.setattr(scanner, "make_scanner", scanner.py_make_scanner)
    raw = '{"model_id":"model","key":' + "[" * 1500 + "0" + "]" * 1500 + "}"
    assert len(raw.encode()) < 4096
    response = api.client.put(
        PATH,
        raw,
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + api.tokens[0],
    )
    assert response.status_code == 400
    assert response.json() == {"error": "Send a valid JSON object"}
    assert not api.provider["calls"] and not api.gateway.reads
    assert not DeveloperProviderKey.objects.exists() and not api.root.exists()


def test_current_definition_and_binding_checks_do_not_transfer_keys(api):
    safe(put(api))
    api.gateway.resource["revision"] += 1
    safe(send(api, "get"))
    assert put(api).status_code == 503
    ModelApproval.objects.update(
        gateway_fingerprint=fingerprint("model", [api.gateway.resource])
    )
    safe(send(api, "get"))
    safe(put(api))
    ModelApproval.objects.all().delete()
    assert put(api).status_code == 403
    safe(send(api, "get"))
    safe(send(api, "delete"), "missing")
    assert len(api.provider["calls"]) == 2


def test_unbound_status_and_cleanup_need_no_gateway_or_provider(api, monkeypatch):
    safe(put(api))
    DeveloperProviderKey.objects.update(validation_fingerprint="")
    ModelApproval.objects.all().delete()
    monkeypatch.setattr(
        api.gateway,
        "request",
        lambda *a, **k: pytest.fail("Metadata must not contact gateway"),
    )
    safe(send(api, "get"))
    safe(send(api, "delete"), "missing")
    assert len(api.provider["calls"]) == 1


@pytest.mark.parametrize(
    "query",
    ["model_id=model&model_id=other", "model_id=model&owner_id=other", "model_id="],
)
def test_get_requires_one_bounded_model_identifier(api, query):
    response = api.client.get(
        PATH + "?" + query, HTTP_AUTHORIZATION="Bearer " + api.tokens[0]
    )
    assert response.status_code == 400 and not api.provider["calls"]


@pytest.mark.parametrize("fault", ["refused", "provider", "file", "database"])
def test_refused_or_failed_replace_preserves_old_key_and_hides_details(
    api, monkeypatch, fault
):
    safe(put(api))
    if fault == "refused":
        api.provider["mode"] = 401
    elif fault == "provider":
        api.provider["mode"] = 500
    elif fault == "file":
        monkeypatch.setattr(
            "model_registry.developer_keys.save",
            lambda *a: (_ for _ in ()).throw(OSError(KEY)),
        )
    else:
        monkeypatch.setattr(
            DeveloperProviderKey,
            "save",
            lambda *a, **k: (_ for _ in ()).throw(DatabaseError(KEY)),
        )
    response = send(api, "put", body={"model_id": "model", "key": KEY + "-new"})
    assert response.status_code == (400 if fault == "refused" else 503)
    assert KEY.encode() not in response.content
    assert [path.read_text() for path in api.root.iterdir()] == [KEY]


def test_pending_cleanup_is_owner_metadata_and_can_be_retried(api, monkeypatch):
    safe(put(api))
    with monkeypatch.context() as patch:
        patch.setattr("model_registry.developer_keys.remove", lambda *a: False)
        response = send(api, "delete")
    assert response.json() == {
        "model_id": "model",
        "status": "missing",
        "cleanup_pending": True,
    }
    safe(send(api, "delete"), "missing")
    assert not DeveloperProviderKey.objects.exists()


def test_cleanup_status_failure_can_follow_a_committed_replacement(api, monkeypatch):
    safe(put(api))
    commit, count = connection.commit, 0

    def fail_cleanup_commit():
        nonlocal count
        count += 1
        if count == 2:
            raise DatabaseError(KEY)
        commit()

    with monkeypatch.context() as patch:
        patch.setattr(connection, "commit", fail_cleanup_commit)
        response = send(api, "put", body={"model_id": "model", "key": KEY + "-new"})
    assert response.status_code == 503 and KEY.encode() not in response.content
    assert [path.read_text() for path in api.root.iterdir()] == [KEY + "-new"]
    result = send(api, "get")
    assert result.json() == {
        "model_id": "model",
        "status": "added",
        "cleanup_pending": True,
    }
    safe(send(api, "delete"), "missing")


def test_insecure_public_origin_refuses_runtime_key_admission(api):
    with override_settings(PUBLIC_ORIGIN="http://keeplane.example"):
        assert put(api).status_code == 503
    assert not api.provider["calls"]
