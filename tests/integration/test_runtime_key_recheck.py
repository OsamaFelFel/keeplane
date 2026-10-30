"""Actual account admission and provider verdicts for checking a saved key."""

import uuid
from types import SimpleNamespace

import pytest
from model_registry import runtime_keys
from model_registry.models import DeveloperProviderKey
from projects.services import DjangoProjectStore

from tests.integration.test_provider_key_validation import provider as provider
from tests.integration.test_runtime_provider_keys import (
    KEY,
    api as api,
    fixture_password_hashes as fixture_password_hashes,
    put,
    safe,
    send,
)

pytestmark = pytest.mark.django_db(transaction=True)
CHECK = "/api/runtime/provider-keys/check"


def check(api, **kwargs):
    return send(api, "post", path=CHECK, **kwargs)


def test_refusal_status_list_owner_isolation_and_recovery(api, monkeypatch):
    safe(put(api))
    original = next(api.root.iterdir())
    safe(check(api, actor=1), "missing")
    assert len(api.provider["calls"]) == 1
    api.provider["mode"] = 401
    safe(check(api), "refused")
    safe(send(api, "get"), "refused")
    assert len(api.provider["calls"]) == 2
    actor = api.identity.session(api.tokens[0])
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(actor["id"], project, "Key check")
    monkeypatch.setattr(
        runtime_keys.runtime_views, "model_policy",
        lambda: SimpleNamespace(eligible_model_ids=lambda _: frozenset({"model"})),
    )
    listed = api.client.get(
        f"/api/runtime/projects/{project}/provider-keys",
        HTTP_AUTHORIZATION="Bearer " + api.tokens[0],
    )
    assert listed.status_code == 200
    assert listed.json()["models"] == [
        {"id": "model", "own_key_required": True, "status": "refused"}
    ]
    assert len(api.provider["calls"]) == 2
    api.provider["mode"] = "accepted"
    safe(check(api))
    assert len(api.provider["calls"]) == 3 and original.read_text() == KEY
    safe(send(api, "delete"), "missing")
    assert not DeveloperProviderKey.objects.exists() and not list(api.root.iterdir())


def test_check_requires_bearer_and_rechecks_withdrawal_before_contact(api, monkeypatch):
    api.client.cookies["keeplane_session"] = api.tokens[0]
    response = api.client.post(CHECK, {"model_id": "model"}, content_type="application/json")
    assert response.status_code == 401
    assert check(api, token="invalid").status_code == 401
    safe(put(api))
    original = runtime_keys.key_store

    def withdrawn(request, model_id):
        api.identity.logout(request.auth)
        return original(request, model_id)

    monkeypatch.setattr(runtime_keys, "key_store", withdrawn)
    assert check(api).status_code == 401
    assert len(api.provider["calls"]) == 1


@pytest.mark.parametrize("extra", ["key", "owner_id", "filename", "fingerprint"])
def test_check_accepts_only_model_id_and_never_a_caller_verdict_or_key(api, extra):
    response = check(api, body={"model_id": "model", extra: KEY})
    assert response.status_code == 400 and KEY.encode() not in response.content
    assert not api.provider["calls"] and not DeveloperProviderKey.objects.exists()


@pytest.mark.parametrize("raw,status", [
    ('{"model_id":"model","model_id":"other"}', 400),
    ('{"model_id":', 400),
    ('x' * 4097, 413),
])
def test_check_refuses_malformed_bodies_without_provider_contact(api, raw, status):
    response = api.client.post(
        CHECK, raw, content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + api.tokens[0],
    )
    assert response.status_code == status and not api.provider["calls"]


def test_provider_outage_keeps_saved_verdict_and_returns_no_details(api):
    safe(put(api))
    api.provider["mode"] = 500
    response = check(api)
    assert response.status_code == 503 and KEY.encode() not in response.content
    safe(send(api, "get"))
    assert not DeveloperProviderKey.objects.get().refused
