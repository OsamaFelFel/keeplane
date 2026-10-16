"""Account withdrawal and recoverable file cleanup use only synthetic keys."""

from io import StringIO

import pytest
from accounts.contracts import IdentityError
from accounts.models import User
from common.errors import StorageUnavailable
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, transaction
from django.db.models.deletion import ProtectedError
from model_registry import key_cleanup
from model_registry.models import DeveloperProviderKey, PendingProviderKeyDeletion

pytestmark = pytest.mark.django_db(transaction=True)
KEY = "synthetic-owner-key"


@pytest.fixture
def owned(domain_services, tmp_path, monkeypatch):
    root = tmp_path / "keys"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("PROVIDER_KEY_DIR", str(root))
    identity = domain_services.identity
    actor = identity.create_user(
        {"username": "owner", "role": "developer", "password": "synthetic-password-123"}
    )
    token = identity.login(actor["username"], "synthetic-password-123")
    other = User.objects.create(username="other", role="developer")
    names = ["key-" + letter * 32 for letter in "abc"]
    for name in names:
        (root / name).write_text(KEY)
        (root / name).chmod(0o600)
    DeveloperProviderKey.objects.create(
        owner_id=actor["id"],
        model_id="model",
        key_name=names[0],
        pending_key_name=names[1],
    )
    DeveloperProviderKey.objects.create(
        owner=other, model_id="model", key_name=names[2]
    )
    return identity, actor, token, other, root, names


def test_removing_account_revokes_sessions_and_cleans_only_its_keys(owned):
    identity, actor, token, other, root, names = owned
    assert identity.delete_user(actor["id"]) == {"removed": True}
    assert identity.session(token) is None
    assert not User.objects.filter(pk=actor["id"]).exists()
    assert not PendingProviderKeyDeletion.objects.exists()
    assert sorted(path.name for path in root.iterdir()) == [names[2]]
    assert DeveloperProviderKey.objects.get(owner=other).key_name == names[2]


def test_rollback_preserves_identity_sessions_files_and_references(owned):
    identity, actor, token, _, root, names = owned
    with pytest.raises(RuntimeError), transaction.atomic():
        identity.delete_user(actor["id"])
        assert PendingProviderKeyDeletion.objects.count() == 2
        assert all((root / name).exists() for name in names)
        raise RuntimeError("synthetic outer rollback")
    assert identity.session(token) is not None
    assert DeveloperProviderKey.objects.filter(owner_id=actor["id"]).exists()
    assert not PendingProviderKeyDeletion.objects.exists()
    assert all((root / name).exists() for name in names)


def test_failed_unlink_keeps_journal_and_command_retries_without_key_output(
    owned, monkeypatch
):
    identity, actor, token, _, root, names = owned
    with monkeypatch.context() as patch:
        patch.setattr(key_cleanup, "unlink_managed", lambda *args: False)
        assert identity.delete_user(actor["id"]) == {"removed": True}
    assert identity.session(token) is None
    assert PendingProviderKeyDeletion.objects.count() == 2
    assert all((root / name).exists() for name in names)
    output = StringIO()
    call_command("cleanup_provider_keys", stdout=output)
    assert output.getvalue() == "Completed 2 key file deletions; 0 pending.\n"
    assert KEY not in output.getvalue() and str(root) not in output.getvalue()
    assert not PendingProviderKeyDeletion.objects.exists()
    assert sorted(path.name for path in root.iterdir()) == [names[2]]


def test_journal_commit_failure_after_unlink_is_retryable(owned, monkeypatch):
    identity, actor, _, _, root, names = owned
    with monkeypatch.context() as patch:

        def failed(*args, **kwargs):
            raise DatabaseError("synthetic journal deletion failure")

        patch.setattr(PendingProviderKeyDeletion, "delete", failed)
        assert identity.delete_user(actor["id"]) == {"removed": True}
    assert PendingProviderKeyDeletion.objects.count() == 2
    assert sum((root / name).exists() for name in names[:2]) == 1
    assert key_cleanup.cleanup_pending() == {"removed": 2, "pending": 0}
    assert sorted(path.name for path in root.iterdir()) == [names[2]]


def test_journal_write_failure_keeps_account_and_all_files(owned, monkeypatch):
    identity, actor, token, _, root, names = owned

    def failed(*args, **kwargs):
        raise DatabaseError("synthetic journal write failure")

    monkeypatch.setattr(PendingProviderKeyDeletion.objects, "create", failed)
    with pytest.raises(StorageUnavailable):
        identity.delete_user(actor["id"])
    assert identity.session(token) is not None
    assert DeveloperProviderKey.objects.filter(owner_id=actor["id"]).exists()
    assert all((root / name).exists() for name in names)


def test_failed_directory_sync_retains_journal_after_account_withdrawal(
    owned, monkeypatch
):
    identity, actor, token, _, root, names = owned
    with monkeypatch.context() as patch:

        def failed(*args):
            raise OSError("synthetic directory sync failure")

        patch.setattr(key_cleanup.os, "fsync", failed)
        assert identity.delete_user(actor["id"]) == {"removed": True}
    assert identity.session(token) is None
    assert PendingProviderKeyDeletion.objects.count() == 2
    assert sorted(path.name for path in root.iterdir()) == [names[2]]
    assert key_cleanup.cleanup_pending() == {"removed": 2, "pending": 0}


def test_unavailable_directory_keeps_pending_files_for_later_retry(owned, monkeypatch):
    identity, actor, _, _, root, names = owned
    offline = root.with_name("offline")
    root.rename(offline)
    assert identity.delete_user(actor["id"]) == {"removed": True}
    assert PendingProviderKeyDeletion.objects.count() == 2
    with pytest.raises(CommandError, match="remain pending"):
        call_command("cleanup_provider_keys", stdout=StringIO())
    offline.rename(root)
    assert key_cleanup.cleanup_pending() == {"removed": 2, "pending": 0}
    assert (root / names[2]).exists()


def test_raw_deletion_remains_protected_and_first_admin_is_never_removed(owned):
    identity, actor, _, _, root, names = owned
    with pytest.raises(ProtectedError):
        User.objects.get(pk=actor["id"]).delete()
    first = User.objects.get(username="first-admin")
    DeveloperProviderKey.objects.create(
        owner=first, model_id="model", key_name=names[0]
    )
    with pytest.raises(IdentityError) as error:
        identity.delete_user(str(first.pk))
    assert error.value.status == 403 and not PendingProviderKeyDeletion.objects.exists()
    assert all((root / name).exists() for name in names)


def test_cleanup_refuses_symlink_directory_and_unmanaged_names(tmp_path):
    root = tmp_path / "keys"
    root.mkdir()
    name = "key-" + "a" * 32
    (root / name).write_text(KEY)
    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    assert not key_cleanup.unlink_managed(str(link), name)
    assert not key_cleanup.unlink_managed(str(root), "../outside")
    assert (root / name).read_text() == KEY


def test_empty_withdrawn_metadata_needs_no_storage_configuration(
    domain_services, monkeypatch
):
    monkeypatch.delenv("PROVIDER_KEY_DIR", raising=False)
    owner = User.objects.create(username="empty-owner", role="developer")
    DeveloperProviderKey.objects.create(owner=owner, model_id="model")
    assert domain_services.identity.delete_user(str(owner.pk)) == {"removed": True}
    assert not DeveloperProviderKey.objects.exists()
    assert not PendingProviderKeyDeletion.objects.exists()
