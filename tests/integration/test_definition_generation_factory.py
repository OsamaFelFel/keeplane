"""Durable key-free candidates; no native writes or provider calls."""

import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from common.errors import StorageUnavailable
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from gateway_publications.factory import (
    HEADER,
    DjangoNativeDefinitionFactory,
    GenerationUnavailable,
    digest,
)
from gateway_publications.models import DefinitionGeneration
from model_registry.fingerprints import fingerprint
from model_registry.models import ModelApproval
from model_registry.policy import ModelPolicyUnavailable
from model_registry.provider_keys import DjangoSharedKeyAvailability

from tests.integration.test_provider_key_validation import setup

pytestmark = pytest.mark.django_db(transaction=True)
WIRING = {
    "config": {"adminAddr": "127.0.0.1:15000"},
    "gateways": {"default": {"bindAddress": "127.0.0.1", "port": 4000}},
    "binds": [{"port": 5000, "entry": {"failureMode": "deny"}}],
    "policies": [{"selected": {"failureMode": "deny"}}],
    "frontendPolicies": {"accessLog": {"database": {"llm": "metadata"}}},
}


def factory_setup(monkeypatch):
    validator, gateway = setup({"url": "https://provider.invalid/v1"})
    wiring = deepcopy(WIRING)
    factory = DjangoNativeDefinitionFactory(
        validator, expected_wiring=WIRING, read_wiring=lambda: deepcopy(wiring)
    )
    monkeypatch.setattr(
        "model_registry.key_validation.subprocess.Popen",
        lambda *a, **k: pytest.fail("A factory must never call the provider"),
    )
    return factory, gateway, wiring


def approve(gateway):
    ModelApproval.objects.update(
        gateway_fingerprint=fingerprint("model", [gateway.resource])
    )


def test_strict_raw_snapshot_and_prepared_envelope_keep_distinct_bindings(monkeypatch):
    factory, gateway, _ = factory_setup(monkeypatch)
    snapshot = factory.validator.raw_definition("model")
    snapshot.value["params"]["model"] = "local-mutation"
    assert gateway.resource["value"]["params"]["model"] == "upstream-model"
    candidate = factory.prepare("model")
    row = DefinitionGeneration.objects.get(pk=candidate.generation)
    assert row.state == "prepared"
    assert candidate.raw_fingerprint == fingerprint("model", [gateway.resource])
    assert candidate.envelope_digest == digest(candidate.value)
    assert candidate.envelope_digest != candidate.raw_fingerprint
    assert candidate.wiring_digest == digest(WIRING)
    rule = candidate.value["authorization"]["rules"][0]["require"]
    assert rule == (
        '(request.method == "GET" && request.path == "/v1/models") || '
        f'request.headers["{HEADER}"] == "{candidate.generation.hex}"'
    )
    assert HEADER in candidate.value["requestHeaders"]["remove"]
    assert "authorization" not in candidate.value["requestHeaders"]["remove"]
    assert "auth" not in candidate.value
    assert factory.require_current(candidate) == candidate
    assert ModelApproval.objects.get().gateway_fingerprint == candidate.raw_fingerprint
    with pytest.raises(ModelPolicyUnavailable, match="key choice is unavailable"):
        DjangoSharedKeyAvailability(gateway, "").require_available("model")


def test_missing_wiring_reader_or_incomplete_expected_wiring_is_refused(monkeypatch):
    factory, _, _ = factory_setup(monkeypatch)
    for expected, reader in (({}, lambda: WIRING), (WIRING, None)):
        with pytest.raises(GenerationUnavailable):
            DjangoNativeDefinitionFactory(
                factory.validator, expected_wiring=expected, read_wiring=reader
            )
    assert not DefinitionGeneration.objects.exists()


@pytest.mark.parametrize("change", ["guard", "key", "revision", "unapproved"])
def test_unsupported_or_unapproved_raw_definition_allocates_nothing(
    monkeypatch, change
):
    factory, gateway, _ = factory_setup(monkeypatch)
    if change == "guard":
        gateway.resource["value"]["authorization"] = {"rules": []}
        approve(gateway)
    elif change == "key":
        gateway.resource["value"]["auth"] = {"key": {"value": {"inline": "synthetic"}}}
        approve(gateway)
    elif change == "revision":
        gateway.resource["revision"] += 1
    else:
        ModelApproval.objects.all().delete()
    with pytest.raises(ValueError):
        factory.prepare("model")
    assert not DefinitionGeneration.objects.exists()


@pytest.mark.parametrize("part", ["entry", "selected", "gateway", "unrelated-global"])
def test_complete_wiring_change_invalidates_preparation(monkeypatch, part):
    factory, _, wiring = factory_setup(monkeypatch)
    candidate = factory.prepare("model")
    if part == "entry":
        wiring["binds"][0]["entry"]["failureMode"] = "allow"
    elif part == "selected":
        wiring["policies"][0]["selected"]["failureMode"] = "allow"
    elif part == "gateway":
        wiring["gateways"]["default"]["bindAddress"] = "0.0.0.0"
    else:
        wiring["frontendPolicies"]["accessLog"]["database"]["llm"] = "full"
    with pytest.raises(GenerationUnavailable, match="wiring changed"):
        factory.require_current(candidate)
    with pytest.raises(GenerationUnavailable):
        factory.prepare("model")
    assert DefinitionGeneration.objects.count() == 1


def test_replacement_removal_and_definition_rollback_never_revive_generations(
    monkeypatch,
):
    factory, gateway, _ = factory_setup(monkeypatch)
    original = deepcopy(gateway.resource)
    first = factory.prepare("model")
    gateway.resource["revision"] += 1
    gateway.resource["value"]["params"]["model"] = "replacement"
    approve(gateway)
    with pytest.raises(GenerationUnavailable):
        factory.require_current(first)
    second = factory.prepare("model")
    factory.retire("model")
    gateway.resource = original  # A controlled rollback still gets a fresh marker.
    approve(gateway)
    third = factory.prepare("model")
    assert len({first.generation, second.generation, third.generation}) == 3
    assert DefinitionGeneration.objects.filter(state="retired").count() == 2
    for candidate in (first, second):
        with pytest.raises(GenerationUnavailable, match="no longer prepared"):
            factory.require_current(candidate)
    assert factory.require_current(third) == third


def test_failed_reservation_remains_burned_and_preserves_previous_candidate(
    monkeypatch,
):
    factory, _, _ = factory_setup(monkeypatch)
    previous = factory.prepare("model")
    with monkeypatch.context() as patch:
        patch.setattr("gateway_publications.factory.envelope", lambda *a: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            factory.prepare("model")
    failed = DefinitionGeneration.objects.get(state="failed")
    assert not failed.envelope and not failed.envelope_digest
    assert factory.require_current(previous) == previous
    with monkeypatch.context() as patch:
        patch.setattr(
            "gateway_publications.factory.uuid.uuid4", lambda: failed.generation
        )
        with pytest.raises(StorageUnavailable):
            factory.prepare("model")
    assert DefinitionGeneration.objects.count() == 2
    assert DefinitionGeneration.objects.get(pk=failed.pk).state == "failed"
    assert factory.require_current(previous) == previous


def test_change_after_reservation_is_retained_failed_not_prepared(monkeypatch):
    factory, gateway, _ = factory_setup(monkeypatch)

    def changed():
        if gateway.reads == 2:
            gateway.resource["revision"] += 1

    gateway.before_read = changed
    with pytest.raises(ValueError, match="changed"):
        factory.prepare("model")
    assert DefinitionGeneration.objects.get().state == "failed"


def test_wiring_change_after_reservation_cannot_replace_previous_candidate(monkeypatch):
    factory, _, wiring = factory_setup(monkeypatch)
    previous = factory.prepare("model")
    reads = 0

    def changed():
        nonlocal reads
        reads += 1
        if reads == 2:
            wiring["policies"] = []
        return deepcopy(wiring)

    factory.read_wiring = changed
    with pytest.raises(GenerationUnavailable, match="wiring changed"):
        factory.prepare("model")
    assert DefinitionGeneration.objects.get(state="prepared").pk == previous.generation
    assert DefinitionGeneration.objects.filter(state="failed").count() == 1
    factory.read_wiring = lambda: deepcopy(WIRING)
    assert factory.require_current(previous) == previous


def test_nested_and_manual_transactions_cannot_return_rollbackable_generations(
    monkeypatch,
):
    factory, _, _ = factory_setup(monkeypatch)
    candidate = factory.prepare("model")
    with transaction.atomic():
        for action in (
            lambda: factory.prepare("model"),
            lambda: factory.retire("model"),
            lambda: factory.reject(candidate.generation),
        ):
            with pytest.raises(GenerationUnavailable, match="own durable transaction"):
                action()
        transaction.set_rollback(True)
    transaction.set_autocommit(False)
    try:
        with pytest.raises(GenerationUnavailable, match="own durable transaction"):
            factory.prepare("model")
    finally:
        connection.rollback()
        transaction.set_autocommit(True)
    assert DefinitionGeneration.objects.count() == 1
    assert factory.require_current(candidate) == candidate


def test_rejection_and_caller_envelope_changes_do_not_mutate_persisted_state(
    monkeypatch,
):
    factory, _, _ = factory_setup(monkeypatch)
    candidate = factory.prepare("model")
    changed = deepcopy(candidate)
    changed.value["params"]["baseUrl"] = "https://elsewhere.invalid/v1"
    with pytest.raises(GenerationUnavailable):
        factory.require_current(changed)
    assert factory.require_current(candidate) == candidate
    factory.reject(candidate.generation)
    with pytest.raises(GenerationUnavailable):
        factory.require_current(candidate)
    replacement = factory.prepare("model")
    assert replacement.generation != candidate.generation
    assert DefinitionGeneration.objects.get(pk=candidate.generation).state == "failed"


def test_fresh_process_reads_committed_candidate_and_retired_history(monkeypatch):
    factory, _, _ = factory_setup(monkeypatch)
    first, second = factory.prepare("model"), factory.prepare("model")
    script = """
import os, sys
sys.path.insert(0, 'components/control-plane')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.test_settings'
from django.conf import settings
settings.DATABASES['default']['NAME'] = sys.argv[1]
import django
django.setup()
from gateway_publications.models import DefinitionGeneration
print(','.join(DefinitionGeneration.objects.order_by('state').values_list('state', flat=True)))
"""
    # Popen is intentionally blocked for provider exchanges above; this child
    # only reads the isolated committed database, so restore the original here.
    monkeypatch.undo()
    result = subprocess.run(
        [sys.executable, "-c", script, str(connection.settings_dict["NAME"])],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout.strip() == "prepared,retired"
    restarted = DjangoNativeDefinitionFactory(
        factory.validator, expected_wiring=WIRING, read_wiring=lambda: deepcopy(WIRING)
    )
    assert restarted.require_current(second) == second
    with pytest.raises(GenerationUnavailable):
        restarted.require_current(first)


def test_initial_migration_preserves_existing_approval():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("gateway_publications", None)])
        approval = ModelApproval.objects.create(
            model_id="existing", key_choice="personal", gateway_fingerprint="a" * 64
        )
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        assert ModelApproval.objects.get(pk=approval.pk).gateway_fingerprint == "a" * 64
        assert DefinitionGeneration.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(latest)
