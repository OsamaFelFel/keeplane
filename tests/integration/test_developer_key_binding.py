"""Provider-checked metadata binds stored keys without exposing key reads."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from accounts.models import User
from common.errors import StorageUnavailable
from model_registry.developer_keys import DeveloperKeyError, DjangoDeveloperKeyStore
from model_registry.fingerprints import fingerprint
from model_registry.models import DeveloperProviderKey
from tests.integration.test_provider_key_validation import KEY, setup
from tests.integration.test_provider_key_validation import provider as provider

pytestmark = pytest.mark.django_db(transaction=True)


def owner_store(provider, tmp_path, monkeypatch):
    validator, gateway = setup(provider)
    monkeypatch.setattr("integrations.gateway.keys.os.fchown", lambda *args: None)
    owner = User.objects.create(username="alice", role="developer")
    root = tmp_path / "keys"
    store = DjangoDeveloperKeyStore(owner.pk, str(root), validate_key=validator)
    return store, root, gateway


def test_real_validation_persists_binding_and_refused_replace_preserves_it(
    provider, tmp_path, monkeypatch
):
    store, root, gateway = owner_store(provider, tmp_path, monkeypatch)
    assert store.put("model", KEY) == {
        "model_id": "model",
        "status": "added",
        "cleanup_pending": False,
    }
    row = DeveloperProviderKey.objects.get(owner_id=store.owner_id)
    assert row.validation_fingerprint == fingerprint("model", [gateway.resource])
    provider["mode"] = 401
    with pytest.raises(DeveloperKeyError, match="provider refused"):
        store.put("model", KEY + "-replacement")
    assert (
        DeveloperProviderKey.objects.get(pk=row.pk).validation_fingerprint
        == row.validation_fingerprint
    )
    assert [path.read_text() for path in root.iterdir()] == [KEY]
    assert len(provider["calls"]) == 2


def test_definition_change_after_check_refuses_replace_before_file_mutation(
    provider, tmp_path, monkeypatch
):
    store, root, gateway = owner_store(provider, tmp_path, monkeypatch)
    store.put("model", KEY)
    validator = store.validate_key

    class ChangedValidator:
        def __call__(self, actor, model, key):
            verified = validator(actor, model, key)
            gateway.resource["revision"] += 1
            return verified

        require_current = validator.require_current

    store.validate_key = ChangedValidator()
    with pytest.raises(DeveloperKeyError, match="current model could not be verified"):
        store.put("model", KEY + "-replacement")
    assert [path.read_text() for path in root.iterdir()] == [KEY]
    assert (
        store.status("model")["status"] == "added"
    )  # Stored metadata, not dispatch admission.


def test_legacy_unbound_key_requires_revalidation_but_can_be_removed(
    provider, tmp_path, monkeypatch
):
    store, root, _ = owner_store(provider, tmp_path, monkeypatch)
    store.put("model", KEY)
    DeveloperProviderKey.objects.update(validation_fingerprint="")
    with pytest.raises(StorageUnavailable, match="requires validation"):
        store.status("model")
    assert store.remove("model")["status"] == "missing" and not list(root.iterdir())


def test_binding_migration_preserves_ownership_and_requires_legacy_revalidation():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    before = [("model_registry", "0003_personal_provider_key_choice")]
    after = [("model_registry", "0004_developer_key_definition")]
    owner = User.objects.create(username="alice", role="developer")
    try:
        executor.migrate(before)
        old = executor.loader.project_state(before).apps.get_model(
            "model_registry", "DeveloperProviderKey"
        )
        row = old.objects.create(
            owner_id=owner.pk,
            model_id="model",
            key_name="key-" + "a" * 32,
            pending_key_name="key-" + "b" * 32,
        )
        original = {
            "owner_id": owner.pk,
            "model_id": "model",
            "key_name": row.key_name,
            "pending_key_name": row.pending_key_name,
        }
        upgraded = MigrationExecutor(connection)
        upgraded.migrate(after)
        new = upgraded.loader.project_state(after).apps.get_model(
            "model_registry", "DeveloperProviderKey"
        )
        current = new.objects.get(pk=row.pk)
        assert {name: getattr(current, name) for name in original} == original
        assert current.validation_fingerprint == ""
    finally:
        MigrationExecutor(connection).migrate(latest)
