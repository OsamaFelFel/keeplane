"""Persist actual write boundaries without admitting protected traffic."""

import json
from copy import deepcopy

import pytest
from common.errors import StorageUnavailable
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from gateway_publications.factory import digest
from gateway_publications.models import DefinitionGeneration, DefinitionPublication
from gateway_publications.publication import (
    DjangoNativePublication,
    PublicationTarget,
    PublicationUnavailable,
)
from model_registry.models import ModelApproval

from tests.integration.test_definition_generation_factory import WIRING, factory_setup

pytestmark = pytest.mark.django_db(transaction=True)
PRIVATE = "synthetic-mismatched-credential-must-not-persist"


class Target:
    def __init__(self, resource, wiring):
        self.store, self.wiring = (
            {"row": deepcopy(resource), "writes": 0},
            deepcopy(wiring),
        )
        self.write_status, self.commit_error = 200, False
        self.after_write = lambda: None
        self.fault, self.reads = "", []

    def request(self, path, body=None, *, method="GET", timeout, connection_retries):
        assert timeout == 5 and connection_retries == 0
        if method == "PUT":
            assert path == "/api/config/resources/llm.model/model"
            if self.write_status == 200 or self.commit_error:
                self.store["writes"] += 1
                self.store["row"]["value"] = deepcopy(body["value"])
                self.store["row"]["revision"] += 1
                self.after_write()
            return self.write_status, {"private": PRIVATE}
        self.reads.append((path, self.store["writes"]))
        if path == "/api/config":
            return 200, deepcopy(self.wiring)
        if path == "/api/config/resources/llm.model":
            row = deepcopy(self.store["row"])
            if self.store["writes"] and self.fault == "missing":
                return 200, {"resources": []}
            if self.store["writes"] and self.fault == "revision":
                row["revision"] = 1
            if self.store["writes"] and self.fault == "secret":
                row["value"]["auth"] = {"key": PRIVATE}
            return 200, {"resources": [row]}
        assert path == "/api/config/effective"
        effective = deepcopy(self.wiring)
        effective.setdefault("llm", {}).setdefault("models", []).append(
            deepcopy(self.store["row"]["value"])
        )
        if self.store["writes"] and self.fault == "effective":
            effective["policies"] = [{"untrusted": PRIVATE}]
        return 200, effective


@pytest.fixture(params=["managed", "existing"])
def trial(request, monkeypatch):
    factory, raw_gateway, _ = factory_setup(monkeypatch)
    wiring = deepcopy(WIRING)
    wiring["llm"] = {
        "models": [
            {
                "name": "customer-owned",
                "provider": "openAI",
                "params": {"model": "unrelated"},
            }
        ]
    }
    targets = {name: Target(raw_gateway.resource, wiring) for name in ("a", "b")}
    factory.expected_wiring_digest = digest(wiring)
    factory.read_wiring = lambda: deepcopy(targets["a"].wiring)
    factory.validator.gateway = targets["a"]
    candidate = factory.prepare("model")

    def publisher(controlled=frozenset({"model"})):
        return DjangoNativePublication(
            factory,
            mode=request.param,
            primary_target="a",
            controlled_model_ids=controlled,
            targets={
                name: PublicationTarget(target, wiring)
                for name, target in targets.items()
            },
        )

    return factory, candidate, targets, publisher


def test_final_readbacks_keep_raw_and_native_fingerprints_separate(trial):
    _, candidate, targets, publisher = trial
    result = publisher().publish(candidate)
    assert result["state"] == "readback_complete"
    row = DefinitionPublication.objects.get()
    assert (
        row.raw_fingerprint
        == ModelApproval.objects.get().gateway_fingerprint
        == candidate.raw_fingerprint
    )
    assert row.envelope_digest == candidate.envelope_digest
    for name, target in targets.items():
        seen = result["targets"][name]
        assert (
            seen["revision"] == 2
            and seen["protected_fingerprint"] != candidate.raw_fingerprint
        )
        assert target.store["row"]["value"] == candidate.value
        assert target.wiring["llm"]["models"][0]["name"] == "customer-owned"
    assert "auth" not in DefinitionGeneration.objects.get().envelope


def test_shared_store_later_puts_require_final_reads_of_every_target(trial):
    _, candidate, targets, publisher = trial
    targets["b"].store = targets["a"].store
    result = publisher().publish(candidate)
    assert {row["revision"] for row in result["targets"].values()} == {3}
    assert (
        len({row["protected_fingerprint"] for row in result["targets"].values()}) == 1
    )
    for target in targets.values():
        assert ("/api/config/resources/llm.model", 2) in target.reads


def test_approval_ownership_flag_is_not_operator_control(trial):
    _, candidate, targets, publisher = trial
    ModelApproval.objects.update(owned_by_keeplane=True)
    with pytest.raises(PublicationUnavailable, match="operator control"):
        publisher(frozenset({"different"})).publish(candidate)
    assert not DefinitionPublication.objects.exists()
    assert all(target.store["writes"] == 0 for target in targets.values())


@pytest.mark.parametrize("change", ["raw", "wiring", "retired"])
def test_failed_preflight_is_retained_without_native_writes(trial, change):
    factory, candidate, targets, publisher = trial
    service = publisher()
    if change == "raw":
        targets["b"].store["row"]["revision"] += 1
    elif change == "wiring":
        targets["b"].wiring["policies"] = []
    else:
        factory.retire("model")
    with pytest.raises(PublicationUnavailable):
        service.publish(candidate)
    assert DefinitionPublication.objects.get().state == "failed"
    assert all(target.store["writes"] == 0 for target in targets.values())


@pytest.mark.parametrize("committed", [False, True])
def test_unconfirmed_partial_writes_are_retained_and_never_replayed(trial, committed):
    _, candidate, targets, publisher = trial
    targets["b"].write_status, targets["b"].commit_error = 503, committed
    with pytest.raises(PublicationUnavailable):
        publisher().publish(candidate)
    row = DefinitionPublication.objects.get()
    assert (
        row.state == "partial" and row.failure == "Publication could not be confirmed"
    )
    assert targets["a"].store["writes"] == 1
    connection.close()
    with pytest.raises(StorageUnavailable):
        publisher().publish(candidate)
    assert DefinitionPublication.objects.count() == 1
    assert targets["a"].store["writes"] == 1
    assert PRIVATE not in json.dumps(row.targets) + row.failure


@pytest.mark.parametrize("fault", ["missing", "revision", "secret", "effective"])
def test_partial_or_stale_final_readback_never_completes_or_persists_raw_bodies(
    trial, fault
):
    _, candidate, targets, publisher = trial
    targets["b"].fault = fault
    with pytest.raises(PublicationUnavailable):
        publisher().publish(candidate)
    row = DefinitionPublication.objects.get()
    assert row.state == "partial"
    assert PRIVATE not in json.dumps(row.targets) + row.failure
    assert ModelApproval.objects.get().gateway_fingerprint == candidate.raw_fingerprint


@pytest.mark.parametrize("change", ["approval", "candidate", "wiring"])
def test_policy_changes_after_first_put_stop_the_remaining_attempt(trial, change):
    factory, candidate, targets, publisher = trial

    def changed():
        if change == "approval":
            ModelApproval.objects.all().delete()
        elif change == "candidate":
            factory.retire("model")
        else:
            targets["b"].wiring["binds"] = []

    targets["a"].after_write = changed
    with pytest.raises(PublicationUnavailable):
        publisher().publish(candidate)
    assert DefinitionPublication.objects.get().state == "partial"
    assert targets["a"].store["writes"] == 1 and targets["b"].store["writes"] == 0


def test_outer_rollback_cannot_hide_a_native_attempt(trial):
    _, candidate, targets, publisher = trial
    with transaction.atomic():
        with pytest.raises(PublicationUnavailable, match="durable"):
            publisher().publish(candidate)
        transaction.set_rollback(True)
    assert not DefinitionPublication.objects.exists()
    assert all(target.store["writes"] == 0 for target in targets.values())


def test_final_database_failure_retains_partial_progress_after_native_writes(
    trial, monkeypatch
):
    _, candidate, targets, publisher = trial
    save = DefinitionPublication.save

    def fail_complete(row, *args, **kwargs):
        if row.state == "readback_complete":
            raise DatabaseError(PRIVATE)
        return save(row, *args, **kwargs)

    monkeypatch.setattr(DefinitionPublication, "save", fail_complete)
    with pytest.raises(PublicationUnavailable):
        publisher().publish(candidate)
    row = DefinitionPublication.objects.get()
    assert row.state == "partial" and PRIVATE not in row.failure
    assert all(target.store["writes"] == 1 for target in targets.values())


def test_publication_migration_preserves_prepared_candidates(monkeypatch):
    factory, _, _ = factory_setup(monkeypatch)
    candidate = factory.prepare("model")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("gateway_publications", "0001_initial")])
        MigrationExecutor(connection).migrate(latest)
        assert (
            DefinitionGeneration.objects.get().raw_fingerprint
            == candidate.raw_fingerprint
        )
        assert factory.require_current(candidate) == candidate
        assert not DefinitionPublication.objects.exists()
    finally:
        MigrationExecutor(connection).migrate(latest)
