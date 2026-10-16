"""Eligibility follows current Django policy, without trusting a client class."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from common.errors import StorageUnavailable
from data_classes.models import ProjectClass, Settings
from django.db import DatabaseError, transaction
from model_registry.fingerprints import fingerprint
from model_registry.models import ModelApproval
from model_registry.policy import DjangoModelPolicy, ModelPolicyUnavailable


@pytest.fixture
def policy(domain_services):
    resources = [
        {"id": name, "revision": 1, "value": {"provider": "openAI"}}
        for name in ("public-model", "private-model", "external-model")
    ]
    state = SimpleNamespace(
        listing={"data": [{"id": row["id"]} for row in resources]},
        registry={"resources": resources},
        status=200,
    )
    gateway = SimpleNamespace(
        models=lambda: (state.status, deepcopy(state.listing)),
        resources=lambda: (state.status, deepcopy(state.registry)),
    )
    domain_services.classes.set_enabled(True)
    for name, classes in (
        ("public-model", ["Public"]),
        ("private-model", ["Confidential"]),
    ):
        domain_services.catalog.approve(name, classes, fingerprint(name, resources))
    ProjectClass.objects.create(project_id="project-a", data_class_id="confidential")
    return DjangoModelPolicy(gateway), state, domain_services


def test_effective_class_comes_from_project_assignment(policy):
    service, _, stores = policy
    assert service.eligible_model_ids("project-a") == {"private-model"}
    assert service.eligible_model_ids("unclassified") == {
        "public-model",
        "private-model",
    }
    stores.classes.set_enabled(False)
    assert service.eligible_model_ids("project-a") == {"public-model", "private-model"}
    stores.classes.set_enabled(True)
    assert service.eligible_model_ids("project-a") == {"private-model"}


def test_only_current_set_up_gateway_models_are_eligible(policy):
    service, state, stores = policy
    state.registry["resources"][1]["revision"] = 2
    assert service.eligible_model_ids("project-a") == set()
    stores.catalog.approve(
        "private-model",
        ["Confidential"],
        fingerprint("private-model", state.registry["resources"]),
    )
    assert service.eligible_model_ids("project-a") == {"private-model"}
    state.listing["data"] = [{"id": "external-model"}]
    assert service.eligible_model_ids("unclassified") == set()


def test_personal_setup_keeps_class_and_definition_gates_without_blocking_other_models(policy):
    service, state, stores = policy
    stores.catalog.approve(
        "external-model", ["Public"],
        fingerprint("external-model", state.registry["resources"]), key_choice="personal",
    )
    assert service.eligible_model_ids("project-a") == {"private-model"}
    assert service.eligible_model_ids("unclassified") == {
        "public-model", "private-model", "external-model",
    }
    state.registry["resources"][2]["revision"] = 2
    assert service.eligible_model_ids("unclassified") == {"public-model", "private-model"}


def test_withdrawal_is_rechecked_by_another_service_instance(policy):
    service, _, stores = policy
    other = DjangoModelPolicy(service.gateway)
    assert other.eligible_model_ids("project-a") == {"private-model"}
    stores.classes.edit(
        "confidential", {"name": "Confidential", "approved_model_ids": []}
    )
    assert service.eligible_model_ids("project-a") == set()
    assert other.eligible_model_ids("project-a") == set()
    stores.classes.set_enabled(False)
    assert other.eligible_model_ids("project-a") == {"public-model", "private-model"}
    stores.catalog.remove("private-model")
    assert other.eligible_model_ids("project-a") == {"public-model"}


def test_rolled_back_policy_change_does_not_withdraw_access(policy):
    service, _, stores = policy
    with pytest.raises(RuntimeError), transaction.atomic():
        stores.catalog.remove("private-model")
        raise RuntimeError("Abort the policy edit")
    assert service.eligible_model_ids("project-a") == {"private-model"}


@pytest.mark.parametrize("broken", ["outage", "models", "resources", "duplicate"])
def test_unverified_gateway_state_fails_closed(policy, broken):
    service, state, _ = policy
    if broken == "outage":
        state.status = 503
    elif broken == "models":
        state.listing = {}
    elif broken == "resources":
        state.registry = {"resources": [None]}
    else:
        state.registry["resources"].append(state.registry["resources"][0])
    with pytest.raises(ModelPolicyUnavailable):
        service.eligible_model_ids("project-a")


def test_missing_settings_are_not_replaced_with_permissive_defaults(policy):
    service, _, _ = policy
    Settings.objects.all().delete()
    with pytest.raises(ModelPolicyUnavailable):
        service.eligible_model_ids("project-a")
    assert not Settings.objects.exists()


@pytest.mark.parametrize("classes", [{}, "Confidential", ["Confidential", 3]])
def test_malformed_model_setup_fails_closed(policy, classes):
    service, _, _ = policy
    ModelApproval.objects.filter(pk="private-model").update(approved_classes=classes)
    with pytest.raises(ModelPolicyUnavailable):
        service.eligible_model_ids("project-a")


def test_storage_failure_produces_no_eligibility_decision(policy, monkeypatch):
    service, _, _ = policy

    def fail(*args, **kwargs):
        raise DatabaseError("Unavailable database")

    monkeypatch.setattr(Settings.objects, "select_for_update", fail)
    with pytest.raises(StorageUnavailable):
        service.eligible_model_ids("project-a")
