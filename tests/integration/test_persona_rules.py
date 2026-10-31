"""Persona rules through Django storage, the admin API and model removal.

Spec 004 ST15 and ST23 (D28, D106, D121) and the Spec 006 ST21 settings-change
record. The plain-English cases are in persona-rule-cases.md.
"""

import json

import pytest
from accounts.models import User
from audit.models import AuditRecord
from django.db import DatabaseError
from model_registry.fingerprints import fingerprint
from model_registry.levels import ModelInUse
from model_registry.models import ModelApproval, PersonaRule
from model_registry.persona_rules import PersonaRuleError
from model_registry.removal import remove_model_setup

from tests.integration.test_complexity_levels import (  # noqa: F401
    ADMIN,
    change,
    levels,
    resource,
)

pytestmark = pytest.mark.django_db


def add_rule(client, persona, model_id, **headers):
    return client.post(
        f"/api/persona-rules/{persona}",
        json.dumps({"model_id": model_id}),
        content_type="application/json",
        **({"HTTP_X_KEEPLANE_ACTION": "1"} | headers),
    )


def listed(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    return response.json()


def settings_records():
    return list(
        AuditRecord.objects.filter(kind="settings")
        .order_by("id")
        .values_list("description", flat=True)
    )


def remove(client, model_id):
    return client.delete(
        f"/api/models/{model_id}/setup",
        "{}",
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )


def test_pr_int_01_add_a_rule_and_it_shows_under_persona_rules(levels):  # noqa: F811
    body = listed(levels.client)
    assert body["persona_rules"] == []
    assert [item["name"] for item in body["personas"]] == [
        "Architect",
        "Developer",
        "Frontend",
    ]
    response = add_rule(levels.client, "architect", "large")
    assert response.status_code == 200
    expected = [
        {
            "persona": "architect",
            "name": "Architect",
            "model_id": "large",
            "model_set_up": True,
        }
    ]
    assert response.json() == {"persona_rules": expected}
    assert listed(levels.client)["persona_rules"] == expected


def test_pr_int_02_records_name_the_admin_and_each_change(levels):  # noqa: F811
    levels.stores.audit.set_option("settings", True)
    assert add_rule(levels.client, "architect", "large").status_code == 200
    # The same rule again changes nothing and records nothing.
    assert add_rule(levels.client, "architect", "large").status_code == 200
    # Adding a rule for a persona that has one moves it.
    assert add_rule(levels.client, "architect", "medium").status_code == 200
    assert add_rule(levels.client, "architect", None).status_code == 200
    assert add_rule(levels.client, "architect", None).status_code == 200
    assert settings_records() == [
        "Added a persona rule for Architect: large",
        "Changed the persona rule for Architect to medium",
        "Removed the persona rule for Architect",
    ]
    assert set(
        AuditRecord.objects.filter(kind="settings").values_list("actor_name", flat=True)
    ) == {"first-admin"}
    assert not PersonaRule.objects.exists()


def test_pr_int_03_no_record_while_settings_changes_are_off(levels):  # noqa: F811
    assert add_rule(levels.client, "frontend", "small").status_code == 200
    assert settings_records() == []
    assert PersonaRule.objects.get(pk="frontend").model_id == "small"


def test_pr_int_04_only_set_up_models_can_be_chosen(levels):  # noqa: F811
    response = add_rule(levels.client, "architect", "gateway-only")
    assert response.status_code == 400
    assert response.json() == {"error": "Choose a model that is set up"}
    levels.gateway.registry[2] = resource("large", revision=2)
    assert add_rule(levels.client, "architect", "large").status_code == 400
    assert not PersonaRule.objects.exists()


def test_pr_int_05_a_rule_whose_model_is_not_set_up_now_stays_recorded(levels):  # noqa: F811
    assert add_rule(levels.client, "architect", "large").status_code == 200
    levels.gateway.registry[2] = resource("large", revision=2)
    assert listed(levels.client)["persona_rules"][0]["model_set_up"] is False
    assert PersonaRule.objects.get(pk="architect").model_id == "large"


def test_pr_int_06_removal_is_refused_while_a_persona_rule_uses_the_model(levels):  # noqa: F811
    levels.stores.audit.set_option("settings", True)
    assert add_rule(levels.client, "architect", "large").status_code == 200
    assert add_rule(levels.client, "frontend", "large").status_code == 200
    assert change(levels.client, "complex", "large").status_code == 200
    before = settings_records()
    response = remove(levels.client, "large")
    assert response.status_code == 409
    assert response.json()["in_use"] == {
        "levels": ["Complex"],
        "persona_rules": ["Architect", "Frontend"],
    }
    assert levels.gateway.deletions == []
    assert ModelApproval.objects.filter(pk="large").exists()
    assert settings_records() == before
    # Moving the level and the rules first lets the removal through.
    assert change(levels.client, "complex", None).status_code == 200
    assert add_rule(levels.client, "architect", "medium").status_code == 200
    response = remove(levels.client, "large")
    assert response.json()["in_use"] == {"levels": [], "persona_rules": ["Frontend"]}
    assert add_rule(levels.client, "frontend", None).status_code == 200
    assert remove(levels.client, "large").status_code == 200
    assert levels.gateway.deletions == ["large"]
    assert settings_records()[-1] == "Removed model large from the gateway"


def test_pr_int_07_outside_model_setup_is_guarded_too(levels):  # noqa: F811
    levels.stores.catalog.approve(
        "gateway-only", [], fingerprint("gateway-only", levels.gateway.registry)
    )
    assert add_rule(levels.client, "developer", "gateway-only").status_code == 200
    status, body = remove_model_setup(
        "gateway-only", ADMIN, levels.stores.catalog, levels.gateway, None, ""
    )
    assert status == 409 and body["in_use"]["persona_rules"] == ["Developer"]
    assert ModelApproval.objects.filter(pk="gateway-only").exists()


def test_pr_int_08_catalog_guard_holds_under_the_settings_lock(levels):  # noqa: F811
    levels.stores.catalog.set_persona_rule("architect", "large", {"large"}, ADMIN)
    with pytest.raises(ModelInUse) as refused:
        levels.stores.catalog.remove(
            "large", ADMIN, remove_from_gateway=lambda: pytest.fail("gateway called")
        )
    assert refused.value.persona_rules == ["Architect"]
    ModelApproval.objects.filter(pk="small").delete()
    with pytest.raises(PersonaRuleError):
        levels.stores.catalog.set_persona_rule("frontend", "small", {"small"}, ADMIN)


def test_pr_int_09_refused_requests_change_nothing(levels):  # noqa: F811
    levels.stores.audit.set_option("settings", True)
    assert add_rule(levels.client, "tester", "small").status_code == 404
    assert add_rule(levels.client, "architect", 7).status_code == 400
    response = levels.client.post(
        "/api/persona-rules/architect",
        json.dumps({"model_id": "small", "persona": "frontend"}),
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )
    assert response.status_code == 400
    for body in (["model_id"], "model_id", None):
        response = levels.client.post(
            "/api/persona-rules/architect",
            json.dumps(body),
            content_type="application/json",
            HTTP_X_KEEPLANE_ACTION="1",
        )
        assert response.status_code == 400, body
        assert response.json() == {"error": "Enter a JSON object"}
    response = levels.client.post(
        "/api/persona-rules/architect",
        json.dumps({"model_id": "small"}),
        content_type="application/json",
    )
    assert response.status_code == 403
    developer = User.objects.create(username="dev", role="developer")
    developer.set_password("synthetic-rule-password")
    developer.save()
    levels.client.cookies["keeplane_session"] = levels.stores.identity.login(
        "dev", "synthetic-rule-password"
    )
    assert add_rule(levels.client, "architect", "small").status_code == 403
    assert not PersonaRule.objects.exists()
    assert settings_records() == []


def test_pr_int_10_record_failure_or_gateway_down_changes_nothing(levels, monkeypatch):  # noqa: F811
    levels.stores.audit.set_option("settings", True)
    real_models = levels.gateway.models
    monkeypatch.setattr(levels.gateway, "models", lambda: (503, {"error": "down"}))
    assert add_rule(levels.client, "architect", "small").status_code == 503
    assert not PersonaRule.objects.exists()
    monkeypatch.setattr(levels.gateway, "models", real_models)

    def failing(*args, **kwargs):
        raise DatabaseError("synthetic-rule-record-failure")

    monkeypatch.setattr("audit.models.AuditRecord.objects.create", failing)
    assert add_rule(levels.client, "architect", "small").status_code == 503
    assert not PersonaRule.objects.exists()
