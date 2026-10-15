"""Owner isolation and failure boundaries of the internal key store."""

import json

from django.db import DatabaseError, transaction
import pytest

from accounts.models import User
from common.errors import StorageUnavailable
from model_registry import developer_keys
from model_registry.developer_keys import DeveloperKeyError, DjangoDeveloperKeyStore
from model_registry.models import DeveloperProviderKey

pytestmark = pytest.mark.django_db(transaction=True)
KEY, REPLACEMENT = "synthetic-provider-key-one", "synthetic-provider-key-two"


@pytest.fixture
def stores(tmp_path, monkeypatch):
    # Host tests retain actual file creation/modes; only the container UID chown
    # is skipped. The native container check covers real uid/gid65532 behavior.
    monkeypatch.setattr("integrations.gateway.keys.os.fchown", lambda *args: None)
    root = tmp_path / "keys"
    owners = [User.objects.create(username=name, role="developer") for name in ("alice", "bob")]
    return [DjangoDeveloperKeyStore(owner.pk, str(root), validate_key=lambda *args: True) for owner in owners], root


def test_owner_isolation_replace_and_remove(stores):
    (alice, bob), root = stores
    assert alice.status("model") == {"model_id": "model", "status": "missing", "cleanup_pending": False}
    result = alice.put("model", KEY)
    bob.put("model", REPLACEMENT)
    assert result["status"] == "added" and len(list(root.iterdir())) == 2
    assert KEY not in json.dumps(result) and REPLACEMENT not in json.dumps(result)
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
    assert root.stat().st_mode & 0o777 == 0o700
    alice.put("model", REPLACEMENT)
    assert len(list(root.iterdir())) == 2
    assert alice.remove("model")["status"] == "missing"
    assert bob.status("model")["status"] == "added" and len(list(root.iterdir())) == 1
    assert alice.remove("model")["status"] == "missing"


@pytest.mark.parametrize("verdict", [False, None, 1])
def test_validation_is_mandatory_and_rejected_replacement_preserves_old_key(stores, verdict):
    (alice, _), root = stores
    alice.put("model", KEY)
    alice.validate_key = lambda *args: verdict
    with pytest.raises(DeveloperKeyError):
        alice.put("model", REPLACEMENT)
    assert [path.read_text() for path in root.iterdir()] == [KEY]
    assert alice.status("model")["status"] == "added"
    with pytest.raises(DeveloperKeyError):
        DjangoDeveloperKeyStore(alice.owner_id, str(root), validate_key=None)


def test_validator_errors_never_return_key_values(stores):
    (alice, _), root = stores
    def refused(*args):
        raise RuntimeError(KEY)
    alice.validate_key = refused
    with pytest.raises(DeveloperKeyError) as error:
        alice.put("model", KEY)
    assert KEY not in str(error.value) and not root.exists()


def test_database_commit_failure_removes_new_file_and_preserves_old_key(stores, monkeypatch):
    (alice, _), root = stores
    alice.put("model", KEY)
    from django.db import connection
    with monkeypatch.context() as patch:
        patch.setattr(connection, "commit", lambda: (_ for _ in ()).throw(DatabaseError("synthetic commit failure")))
        with pytest.raises(StorageUnavailable):
            alice.put("model", REPLACEMENT)
    assert [path.read_text() for path in root.iterdir()] == [KEY]
    assert alice.status("model")["status"] == "added"


def test_cleanup_failure_retains_reference_and_can_be_retried(stores, monkeypatch):
    (alice, _), root = stores
    alice.put("model", KEY)
    with monkeypatch.context() as patch:
        patch.setattr(developer_keys, "remove", lambda *args: False)
        result = alice.put("model", REPLACEMENT)
        assert result["status"] == "added" and result["cleanup_pending"]
        assert len(list(root.iterdir())) == 2
        with pytest.raises(StorageUnavailable):
            alice.put("model", KEY)
    assert alice.remove("model") == {"model_id": "model", "status": "missing", "cleanup_pending": False}
    assert not list(root.iterdir()) and not DeveloperProviderKey.objects.exists()


def test_failed_delete_cleanup_withdraws_active_reference(stores, monkeypatch):
    (alice, _), root = stores
    alice.put("model", KEY)
    with monkeypatch.context() as patch:
        patch.setattr(developer_keys, "remove", lambda *args: False)
        assert alice.remove("model") == {"model_id": "model", "status": "missing", "cleanup_pending": True}
        assert DeveloperProviderKey.objects.get(owner_id=alice.owner_id).key_name == ""
        assert list(root.iterdir())
    alice.remove("model")
    assert not list(root.iterdir())


def test_storage_outage_and_inactive_owner_fail_without_replacing_key(stores, monkeypatch):
    (alice, _), root = stores
    alice.put("model", KEY)
    with monkeypatch.context() as patch:
        patch.setattr(developer_keys, "save", lambda *args: (_ for _ in ()).throw(OSError("synthetic storage failure")))
        with pytest.raises(StorageUnavailable):
            alice.put("model", REPLACEMENT)
    User.objects.filter(pk=alice.owner_id).update(is_active=False)
    with pytest.raises(DeveloperKeyError):
        alice.put("model", REPLACEMENT)
    assert [path.read_text() for path in root.iterdir()] == [KEY]


def test_mutation_rejects_outer_transaction_before_writing(stores):
    (alice, _), root = stores
    with transaction.atomic():
        with pytest.raises(RuntimeError):
            alice.put("model", KEY)
    assert not root.exists() and not DeveloperProviderKey.objects.exists()


def test_pending_cleanup_is_retryable_after_transaction_rollback(stores, monkeypatch):
    (alice, _), root = stores
    alice.put("model", KEY)
    with monkeypatch.context() as patch:
        patch.setattr(developer_keys, "remove", lambda *args: False)
        alice.put("model", REPLACEMENT)
    from django.db import connection
    with monkeypatch.context() as patch:
        patch.setattr(connection, "commit", lambda: (_ for _ in ()).throw(DatabaseError("rollback")))
        with pytest.raises(StorageUnavailable):
            alice.put("model", KEY)
    # The old pending file was deleted before rollback restored its reference.
    assert alice.status("model")["cleanup_pending"]
    assert [path.read_text() for path in root.iterdir()] == [REPLACEMENT]
    assert alice.remove("model")["status"] == "missing"
    assert not list(root.iterdir()) and not DeveloperProviderKey.objects.exists()


def test_cleanup_database_failure_reports_already_committed_state(stores, monkeypatch):
    (alice, _), root = stores
    from django.db import connection
    commit, calls = connection.commit, []
    def fail_second_commit():
        calls.append(True)
        if len(calls) == 2:
            raise DatabaseError("cleanup commit failure")
        commit()
    with monkeypatch.context() as patch:
        patch.setattr(connection, "commit", fail_second_commit)
        with pytest.raises(StorageUnavailable, match="Key state changed"):
            alice.put("model", KEY)
    assert alice.status("model")["status"] == "added"
    assert [path.read_text() for path in root.iterdir()] == [KEY]


def test_rollback_and_unlink_failure_explicitly_report_unreferenced_file(stores, monkeypatch):
    (alice, _), root = stores
    from django.db import connection
    with monkeypatch.context() as patch:
        patch.setattr(connection, "commit", lambda: (_ for _ in ()).throw(DatabaseError("rollback")))
        patch.setattr(developer_keys, "remove", lambda *args: False)
        with pytest.raises(StorageUnavailable, match="not saved; temporary-key cleanup failed"):
            alice.put("model", KEY)
    assert alice.status("model")["status"] == "missing"
    assert not DeveloperProviderKey.objects.exists()
    assert [path.read_text() for path in root.iterdir()] == [KEY]  # Operator recovery required.


def test_owner_deletion_requires_key_cleanup(stores, domain_services):
    from django.db.models.deletion import ProtectedError
    (alice, _), root = stores
    alice.put("model", KEY)
    # No HTTP key admission exists. Account-removal integration is a prerequisite;
    # until then PROTECT prevents silently orphaning a provider credential.
    with pytest.raises(StorageUnavailable) as error:
        domain_services.identity.delete_user(str(alice.owner_id))
    assert isinstance(error.value.__cause__, ProtectedError)
    assert alice.status("model")["status"] == "added"
    alice.remove("model")
    assert domain_services.identity.delete_user(str(alice.owner_id)) == {"removed": True}
    assert not list(root.iterdir())
