"""Complexity levels through Django storage, the admin API and model removal.

Spec 004 ST13 and ST23 (D104, D121) and Spec 006 ST21. The plain-English
cases are in complexity-level-cases.md.
"""

import json
from types import SimpleNamespace

import pytest
from accounts.models import User
from audit.models import AuditRecord
from common.errors import StorageUnavailable
from django.db import DatabaseError
from django.test import Client
from model_registry import views
from model_registry.fingerprints import fingerprint
from model_registry.levels import LevelError, ModelInUse
from model_registry.models import ComplexityLevelChoice, ModelApproval
from model_registry.registration import ModelManagement
from model_registry.removal import remove_model_setup

from integrations import runners

pytestmark = pytest.mark.django_db

ADMIN = ("admin-id", "level-admin")


def resource(model_id, revision=1):
    return {
        "id": model_id,
        "revision": revision,
        "value": {
            "provider": {"custom": {"formats": [{"type": "completions"}]}},
            "params": {"model": model_id, "baseUrl": "http://model:18080/v1"},
        },
    }


class Gateway:
    """An in-memory gateway: listed models and their definitions."""

    def __init__(self, *model_ids, outside=()):
        self.registry = [resource(model_id) for model_id in (*model_ids, *outside)]
        self.deletions = []

    def models(self):
        return 200, {"data": [{"id": item["id"]} for item in self.registry]}

    def resources(self):
        return 200, {"resources": self.registry}

    def delete_model(self, model_id):
        self.deletions.append(model_id)
        self.registry = [item for item in self.registry if item["id"] != model_id]
        return 200, {}


@pytest.fixture
def levels(domain_services, monkeypatch):
    stores = domain_services
    gateway = Gateway("small", "medium", "large", outside=["gateway-only"])
    for model_id, tokens in (("small", 4096), ("medium", 32768), ("large", 131072)):
        stores.catalog.approve(
            model_id,
            [],
            fingerprint(model_id, gateway.registry),
            owned_by_keeplane=True,
            context_tokens=tokens,
        )
    monkeypatch.setattr("common.api.IDENTITY", stores.identity)
    monkeypatch.setattr(views, "CATALOG", stores.catalog)
    monkeypatch.setattr(views, "MODEL_GATEWAY", gateway)
    monkeypatch.setattr(views, "RUNNER_URLS", set())
    client = Client(HTTP_HOST="127.0.0.1")
    client.cookies["keeplane_session"] = stores.identity.login(
        "first-admin", "first-test-password-123"
    )
    return SimpleNamespace(stores=stores, gateway=gateway, client=client)


def get_levels(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    return {row["level"]: row for row in response.json()["levels"]}


def change(client, level, model_id, **headers):
    return client.post(
        f"/api/levels/{level}",
        json.dumps({"model_id": model_id}),
        content_type="application/json",
        **({"HTTP_X_KEEPLANE_ACTION": "1"} | headers),
    )


def summary(rows):
    return {
        level: (row["model_id"], row["changed_by_admin"]) for level, row in rows.items()
    }


def settings_records():
    return list(
        AuditRecord.objects.filter(kind="settings")
        .order_by("id")
        .values_list("description", flat=True)
    )


def test_cl_int_01_models_and_routing_shows_keeplanes_picks(levels):
    assert summary(get_levels(levels.client)) == {
        "simple": ("small", False),
        "standard": ("medium", False),
        "complex": ("large", False),
    }


def test_cl_int_02_gateway_only_and_changed_models_are_never_picked(levels):
    # "gateway-only" is listed by the gateway but never set up; it would rank
    # first by model ID if it were a candidate.
    rows = get_levels(levels.client)
    assert "gateway-only" not in {row["keeplane_pick"] for row in rows.values()}
    response = change(levels.client, "simple", "gateway-only")
    assert response.status_code == 400
    assert response.json() == {"error": "Choose a model that is set up"}
    # A set-up model whose gateway definition changed is not set up now.
    levels.gateway.registry[2] = resource("large", revision=2)
    rows = get_levels(levels.client)
    assert rows["complex"]["model_id"] == "medium"
    assert change(levels.client, "complex", "large").status_code == 400
    assert not ComplexityLevelChoice.objects.exists()


def test_cl_int_03_change_a_pick_and_go_back(levels):
    levels.stores.audit.set_option("settings", True)
    response = change(levels.client, "complex", "small")
    assert response.status_code == 200
    rows = {row["level"]: row for row in response.json()["levels"]}
    assert rows["complex"]["model_id"] == "small"
    assert rows["complex"]["changed_by_admin"] is True
    assert rows["complex"]["keeplane_pick"] == "large"
    assert summary(get_levels(levels.client))["complex"] == ("small", True)
    # Saving the same choice again changes nothing and records nothing.
    assert change(levels.client, "complex", "small").status_code == 200
    assert change(levels.client, "complex", "medium").status_code == 200
    response = change(levels.client, "complex", None)
    assert response.status_code == 200
    assert summary(get_levels(levels.client))["complex"] == ("large", False)
    assert change(levels.client, "complex", None).status_code == 200
    assert settings_records() == [
        "Changed complexity pick Complex: Keeplane's pick to model small",
        "Changed complexity pick Complex: model small to model medium",
        "Changed complexity pick Complex: model medium to Keeplane's pick",
    ]
    assert set(
        AuditRecord.objects.filter(kind="settings").values_list("actor_name", flat=True)
    ) == {"first-admin"}


def test_cl_int_04_no_record_while_settings_changes_are_off(levels):
    assert change(levels.client, "simple", "large").status_code == 200
    assert settings_records() == []
    assert ComplexityLevelChoice.objects.get(pk="simple").model_id == "large"


def test_cl_int_05_keeplanes_picks_follow_models_but_admin_picks_stay(levels):
    assert change(levels.client, "simple", "medium").status_code == 200
    levels.gateway.registry.append(resource("tiny"))
    levels.stores.catalog.approve(
        "tiny", [], fingerprint("tiny", levels.gateway.registry), context_tokens=1024
    )
    levels.gateway.registry.append(resource("huge"))
    levels.stores.catalog.approve(
        "huge", [], fingerprint("huge", levels.gateway.registry), context_tokens=1000000
    )
    rows = get_levels(levels.client)
    assert summary(rows) == {
        "simple": ("medium", True),
        "standard": ("medium", False),
        "complex": ("huge", False),
    }
    assert rows["simple"]["keeplane_pick"] == "tiny"
    # Removing a model on Keeplane's own pick is allowed; the level picks again.
    status, _ = remove_model_setup(
        "huge", ADMIN, levels.stores.catalog, levels.gateway, None, ""
    )
    assert status == 200
    assert summary(get_levels(levels.client))["complex"] == ("large", False)
    # Editing a model's setup keeps the context window the runner reported.
    levels.stores.catalog.approve(
        "medium", [], fingerprint("medium", levels.gateway.registry), key_choice="none"
    )
    assert ModelApproval.objects.get(pk="medium").context_tokens == 32768


def test_cl_int_06_removal_is_refused_while_an_admin_changed_level_uses_the_model(
    levels,
):
    levels.stores.audit.set_option("settings", True)
    assert change(levels.client, "simple", "large").status_code == 200
    assert change(levels.client, "complex", "large").status_code == 200
    before = settings_records()
    response = levels.client.delete(
        "/api/models/large/setup",
        "{}",
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )
    assert response.status_code == 409
    assert response.json()["in_use"] == {
        "levels": ["Simple", "Complex"],
        "persona_rules": [],
    }
    assert levels.gateway.deletions == []
    assert ModelApproval.objects.filter(pk="large").exists()
    assert settings_records() == before
    # Moving the levels first lets the removal through.
    assert change(levels.client, "simple", None).status_code == 200
    assert change(levels.client, "complex", "medium").status_code == 200
    response = levels.client.delete(
        "/api/models/large/setup",
        "{}",
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )
    assert response.status_code == 200
    assert levels.gateway.deletions == ["large"]
    assert settings_records()[-1] == "Removed model large from the gateway"


def test_cl_int_07_outside_model_setup_is_guarded_too(levels):
    levels.stores.catalog.approve(
        "gateway-only", [], fingerprint("gateway-only", levels.gateway.registry)
    )
    assert change(levels.client, "standard", "gateway-only").status_code == 200
    status, body = remove_model_setup(
        "gateway-only", ADMIN, levels.stores.catalog, levels.gateway, None, ""
    )
    assert status == 409 and body["in_use"]["levels"] == ["Standard"]
    assert ModelApproval.objects.filter(pk="gateway-only").exists()


def test_cl_int_08_catalog_guard_holds_under_the_settings_lock(levels):
    # Even a caller that skipped the early check can't remove the model.
    levels.stores.catalog.change_level("complex", "large", {"large"}, ADMIN)
    with pytest.raises(ModelInUse) as refused:
        levels.stores.catalog.remove(
            "large", ADMIN, remove_from_gateway=lambda: pytest.fail("gateway called")
        )
    assert refused.value.levels == ["Complex"]
    assert ModelApproval.objects.filter(pk="large").exists()
    # A level can't be changed to a model whose setup is already gone.
    ModelApproval.objects.filter(pk="small").delete()
    with pytest.raises(LevelError):
        levels.stores.catalog.change_level("simple", "small", {"small"}, ADMIN)


def test_cl_int_09_refused_requests_change_nothing(levels):
    levels.stores.audit.set_option("settings", True)
    assert change(levels.client, "expert", "small").status_code == 404
    assert change(levels.client, "simple", 7).status_code == 400
    response = levels.client.post(
        "/api/levels/simple",
        json.dumps({"model_id": "small", "extra": True}),
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )
    assert response.status_code == 400
    for body in (["model_id"], "model_id", None):
        response = levels.client.post(
            "/api/levels/simple",
            json.dumps(body),
            content_type="application/json",
            HTTP_X_KEEPLANE_ACTION="1",
        )
        assert response.status_code == 400, body
        assert response.json() == {"error": "Enter a JSON object"}
    response = levels.client.post(
        "/api/levels/simple",
        json.dumps({"model_id": "small"}),
        content_type="application/json",
    )
    assert response.status_code == 403
    developer = User.objects.create(username="dev", role="developer")
    developer.set_password("synthetic-level-password")
    developer.save()
    levels.client.cookies["keeplane_session"] = levels.stores.identity.login(
        "dev", "synthetic-level-password"
    )
    assert change(levels.client, "simple", "small").status_code == 403
    assert levels.client.get("/api/models").status_code == 403
    assert not ComplexityLevelChoice.objects.exists()
    assert settings_records() == []


def test_cl_int_10_record_or_storage_failure_changes_nothing(levels, monkeypatch):
    levels.stores.audit.set_option("settings", True)

    def failing(*args, **kwargs):
        raise DatabaseError("synthetic-level-record-failure")

    monkeypatch.setattr("audit.models.AuditRecord.objects.create", failing)
    response = change(levels.client, "complex", "small")
    assert response.status_code == 503
    assert not ComplexityLevelChoice.objects.exists()
    monkeypatch.undo()
    monkeypatch.setattr("common.api.IDENTITY", levels.stores.identity)
    monkeypatch.setattr(views, "CATALOG", levels.stores.catalog)
    monkeypatch.setattr(views, "MODEL_GATEWAY", levels.gateway)
    monkeypatch.setattr(views, "RUNNER_URLS", set())
    monkeypatch.setattr(
        "model_registry.catalog.ComplexityLevelChoice.objects.values_list", failing
    )
    with pytest.raises(StorageUnavailable):
        levels.stores.catalog.level_choices()
    assert levels.client.get("/api/models").status_code == 503


def test_cl_int_11_gateway_down_changes_nothing(levels, monkeypatch):
    monkeypatch.setattr(levels.gateway, "models", lambda: (503, {"error": "down"}))
    assert change(levels.client, "simple", "small").status_code == 503
    assert not ComplexityLevelChoice.objects.exists()


def test_cl_int_12_runner_context_is_recorded_when_a_local_model_is_added(
    domain_services, monkeypatch
):
    """Add model keeps the context a single-model runner reports; nothing else."""
    stores = domain_services
    calls = []

    def fake_runner(address, allowed, model=None):
        calls.append(model)
        if model is None:
            return 200, {
                "models": ["coder"],
                "runtime": {"coder": {"active_context_tokens": 16384}},
            }
        return 200, {"models": ["coder"]}

    monkeypatch.setattr(runners, "local_runner", fake_runner)
    monkeypatch.setattr("model_registry.registration.local_runner", fake_runner)
    registry = []

    class Recording:
        def request(self, path, body=None, method="GET", timeout=None):
            if path == "/v1/models":
                return 200, {"data": [{"id": item["id"]} for item in registry]}
            registry.append(
                {
                    "id": body["resources"][0]["value"]["id"],
                    "revision": 1,
                    "value": body["resources"][0]["value"],
                }
            )
            return 200, {}

        def resources(self):
            return 200, {"resources": registry}

    management = ModelManagement(
        stores.catalog,
        stores.classes,
        Recording(),
        ADMIN,
        "managed",
        None,
        "",
        {"http://runner:8080"},
        {"openai": "", "anthropic": ""},
        "",
    )
    monkeypatch.setattr(
        management,
        "confirm_new_model",
        lambda name, params: fingerprint(name, registry),
    )
    status, body = management.add(
        {
            "name": "coder",
            "model": "coder",
            "source": "runner",
            "address": "http://runner:8080",
        }
    )
    assert status == 200, body
    assert ModelApproval.objects.get(pk="coder").context_tokens == 16384
    assert calls == ["coder", None]
    assert stores.catalog.context_windows(["coder", "missing"]) == {
        "coder": 16384,
        "missing": None,
    }


def test_cl_int_13_invalid_context_window_is_refused(domain_services):
    for value in (0, -1, "4096", 1.5, True):
        with pytest.raises(ValueError):
            domain_services.catalog.approve(
                "bad", [], "definition", context_tokens=value
            )
    assert not ModelApproval.objects.filter(pk="bad").exists()
