"""Admin counts current-bound registrations without returning owner/key data."""

import json
from types import SimpleNamespace

import pytest
from django.db import DatabaseError
from django.test import Client

from accounts.models import User
from common.errors import StorageUnavailable
from model_registry import views
from model_registry.fingerprints import fingerprint
from model_registry.listing import list_models
from model_registry.models import DeveloperProviderKey, ModelApproval

pytestmark = pytest.mark.django_db


@pytest.fixture
def counts(domain_services):
    resource = {
        "id": "personal-model",
        "revision": 1,
        "value": {"provider": "openAI", "params": {"model": "upstream-model"}},
    }
    digest = fingerprint("personal-model", [resource])
    catalog = domain_services.catalog
    catalog.approve("personal-model", [], digest, key_choice="personal")
    for name, role, active, model, binding, key_name in (
        ("alice", "developer", True, "personal-model", digest, "key-" + "a" * 32),
        ("bob-admin", "admin", True, "personal-model", digest, "key-" + "b" * 32),
        (
            "inactive-owner",
            "developer",
            False,
            "personal-model",
            digest,
            "key-" + "c" * 32,
        ),
        (
            "changed-definition",
            "developer",
            True,
            "personal-model",
            "d" * 64,
            "key-" + "d" * 32,
        ),
        ("unbound-owner", "developer", True, "personal-model", "", "key-" + "e" * 32),
        ("withdrawn-owner", "developer", True, "personal-model", digest, ""),
        (
            "other-model-owner",
            "developer",
            True,
            "other-model",
            digest,
            "key-" + "f" * 32,
        ),
    ):
        owner = User.objects.create(username=name, role=role, is_active=active)
        DeveloperProviderKey.objects.create(
            owner=owner,
            model_id=model,
            validation_fingerprint=binding,
            key_name=key_name,
            pending_key_name="key-" + "0" * 32,
        )
    gateway = SimpleNamespace(
        models=lambda: (200, {"data": [{"id": "personal-model"}]}),
        resources=lambda: (200, {"resources": [resource]}),
    )
    return SimpleNamespace(
        stores=domain_services,
        catalog=catalog,
        gateway=gateway,
        resource=resource,
        digest=digest,
    )


def test_count_is_one_current_bound_query_and_get_contract_stays_unchanged(
    counts, django_assert_num_queries
):
    previous = counts.catalog.get("personal-model")
    with django_assert_num_queries(1):
        assert counts.catalog.personal_key_count("personal-model", counts.digest) == 2
    assert counts.catalog.get("personal-model") == previous
    assert set(previous) == {
        "key_choice",
        "approved_classes",
        "gateway_fingerprint",
        "owned_by_keeplane",
    }
    User.objects.filter(username="alice").update(is_active=False)
    assert counts.catalog.personal_key_count("personal-model", counts.digest) == 1
    ModelApproval.objects.update(gateway_fingerprint="1" * 64)
    assert counts.catalog.personal_key_count("personal-model", counts.digest) == 0
    assert counts.catalog.personal_key_count("personal-model", "") == 0
    ModelApproval.objects.update(gateway_fingerprint=counts.digest, key_choice="shared")
    assert counts.catalog.personal_key_count("personal-model", counts.digest) == 0


def test_listing_count_contains_no_owner_key_or_stale_model_data(counts):
    status, body = list_models(
        counts.gateway.models, counts.gateway.resources, counts.catalog, None, set()
    )
    assert status == 200 and body["models"][0]["developer_key_count"] == 2
    encoded = json.dumps(body)
    for private in ("alice", "bob-admin", "key-" + "a" * 32, counts.digest):
        assert private not in encoded
    counts.resource["revision"] = 2
    _, body = list_models(
        counts.gateway.models, counts.gateway.resources, counts.catalog, None, set()
    )
    assert not body["models"][0]["approved"]
    assert "developer_key_count" not in body["models"][0]


def test_admin_http_count_is_read_only_and_unavailable_storage_never_invents_zero(
    counts, monkeypatch
):
    monkeypatch.setattr("common.api.IDENTITY", counts.stores.identity)
    monkeypatch.setattr(views, "CATALOG", counts.catalog)
    monkeypatch.setattr(views, "MODEL_GATEWAY", counts.gateway)
    client = Client(HTTP_HOST="127.0.0.1")
    assert client.get("/api/models").status_code == 401
    alice = User.objects.get(username="alice")
    alice.set_password("synthetic-count-password")
    alice.save()
    client.cookies["keeplane_session"] = counts.stores.identity.login(
        "alice", "synthetic-count-password"
    )
    assert client.get("/api/models").status_code == 403
    client.cookies["keeplane_session"] = counts.stores.identity.login(
        "first-admin", "first-test-password-123"
    )
    response = client.get("/api/models")
    assert (
        response.status_code == 200
        and response.json()["models"][0]["developer_key_count"] == 2
    )

    def unavailable(*args, **kwargs):
        raise DatabaseError("synthetic-count-storage-outage")

    monkeypatch.setattr("django.db.models.query.QuerySet.count", unavailable)
    with pytest.raises(StorageUnavailable):
        counts.catalog.personal_key_count("personal-model", counts.digest)
    response = client.get("/api/models")
    assert (
        response.status_code == 503
        and "developer_key_count" not in response.content.decode()
    )
