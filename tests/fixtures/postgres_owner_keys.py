"""Real PostgreSQL locks and file cleanup; provider validation is synthetic."""

import json
import os
import shutil
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from accounts.models import User
from common.stores import stores
from django.core.management import call_command
from django.db import connection, connections, transaction
from model_registry.developer_keys import DjangoDeveloperKeyStore
from model_registry.key_validation import VerifiedProviderKey
from model_registry.models import (
    DeveloperProviderKey,
    ModelApproval,
    PendingProviderKeyDeletion,
)

MODEL = "postgres-owner-key-" + uuid.uuid4().hex
DIGEST = "a" * 64
HELD, RELEASE, STARTED = Event(), Event(), Event()


class SyntheticValidator:
    def __init__(self, wait=False, announce=False):
        self.wait, self.announce = wait, announce

    def __call__(self, owner_id, model_id, value):
        if self.announce:
            STARTED.set()
        return VerifiedProviderKey(owner_id, model_id, DIGEST)

    def require_current(self, verification):
        assert connection.in_atomic_block
        approval = ModelApproval.objects.select_for_update().get(pk=MODEL)
        assert approval.key_choice == "personal"
        assert approval.gateway_fingerprint == verification.definition_fingerprint
        if self.wait:
            HELD.set()
            assert RELEASE.wait(30), "First fixture writer was not released"


def run():
    assert connection.vendor == "postgresql"
    # The fixture starts as root only to read its existing Compose secrets.
    # All key operations, including chown, run under the actual app UID.
    _, identity, _, _ = stores()
    root = Path(tempfile.mkdtemp(prefix="keeplane-owner-keys-"))
    os.chown(root, 65532, 65532)
    os.setgroups([])
    os.setgid(65532)
    os.setuid(65532)
    assert os.geteuid() == 65532
    os.environ["PROVIDER_KEY_DIR"] = str(root)
    people = []
    results = []

    def store(owner, **options):
        return DjangoDeveloperKeyStore(
            owner.pk, str(root), validate_key=SyntheticValidator(**options)
        )

    def record(identifier, **observed):
        results.append({"case": identifier, "verdict": "pass", **observed})

    try:
        ModelApproval.objects.create(
            model_id=MODEL, key_choice="personal", gateway_fingerprint=DIGEST
        )
        for label in ("a", "b"):
            actor = identity.create_user(
                {
                    "username": "key-" + label + "-" + uuid.uuid4().hex[:12],
                    "password": "synthetic-postgres-password",
                    "role": "developer",
                }
            )
            people.append(User.objects.get(pk=actor["id"]))
        alice, bob = people
        alice_store, bob_store = store(alice), store(bob)
        token = identity.login(alice.username, "synthetic-postgres-password")
        alice_store.put(MODEL, "synthetic-postgres-alice")
        bob_store.put(MODEL, "synthetic-postgres-bob")
        before = DeveloperProviderKey.objects.get(owner=bob, model_id=MODEL).key_name
        alice_store.put(MODEL, "synthetic-postgres-alice-replacement")
        assert len(list(root.iterdir())) == 2
        for path in root.iterdir():
            stat = path.stat()
            assert stat.st_uid == stat.st_gid == 65532
            assert stat.st_mode & 0o777 == 0o600 and stat.st_nlink == 1
        assert root.stat().st_mode & 0o777 == 0o700
        assert alice_store.status(MODEL)["status"] == "added"
        connections.close_all()
        assert bob_store.status(MODEL)["status"] == "added"
        assert list(
            DeveloperProviderKey.objects.filter(model_id=MODEL).values_list(
                "validation_fingerprint", flat=True
            )
        ) == [DIGEST, DIGEST]
        record("PGKEY-01", uid=65532, isolated_owners=True, persistent_binding=True)

        def writer(label, **options):
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('application_name', %s, false)", [label]
                    )
                return store(alice, **options).put(MODEL, "synthetic-" + label)
            finally:
                connections.close_all()

        second_label = "keeplane-key-waiter-" + uuid.uuid4().hex[:12]
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(writer, "keeplane-key-first", wait=True)
            try:
                assert HELD.wait(10), "First fixture writer did not acquire its lock"
                second = executor.submit(writer, second_label, announce=True)
                assert STARTED.wait(10), "Second fixture writer did not start"
                deadline = time.monotonic() + 10
                while True:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE application_name = %s",
                            [second_label],
                        )
                        blocked = any(row[0] == "Lock" for row in cursor.fetchall())
                    if blocked:
                        break
                    assert time.monotonic() < deadline, (
                        "Second writer did not wait on PostgreSQL"
                    )
                    time.sleep(0.05)
                assert not second.done()
            finally:
                RELEASE.set()
            assert first.result(timeout=15)["status"] == "added"
            assert second.result(timeout=15)["status"] == "added"
        row = DeveloperProviderKey.objects.get(owner=alice, model_id=MODEL)
        assert not row.pending_key_name and row.validation_fingerprint == DIGEST
        assert {path.name for path in root.iterdir()} == {row.key_name, before}
        record("PGKEY-02", database_lock_observed=True, concurrent_replacements=True)

        try:
            with transaction.atomic():
                identity.delete_user(alice.pk)
                assert PendingProviderKeyDeletion.objects.count() == 1
                assert (root / row.key_name).exists()
                raise RuntimeError("synthetic-account-rollback")
        except RuntimeError as error:
            assert str(error) == "synthetic-account-rollback"
        assert identity.session(token) is not None
        assert User.objects.filter(pk=alice.pk).exists()
        restored = DeveloperProviderKey.objects.get(owner=alice, model_id=MODEL)
        assert restored.key_name == row.key_name
        assert restored.validation_fingerprint == DIGEST
        assert not restored.pending_key_name
        assert (root / restored.key_name).exists()
        assert not PendingProviderKeyDeletion.objects.exists()
        record("PGKEY-03", account_session_and_file_rollback=True)

        with patch("model_registry.key_cleanup.unlink_managed", return_value=False):
            identity.delete_user(alice.pk)
        assert identity.session(token) is None
        assert not User.objects.filter(pk=alice.pk).exists()
        assert PendingProviderKeyDeletion.objects.count() == 1
        connections.close_all()
        assert PendingProviderKeyDeletion.objects.count() == 1
        assert (root / row.key_name).exists()
        output = StringIO()
        call_command("cleanup_provider_keys", stdout=output)
        assert output.getvalue() == "Completed 1 key file deletions; 0 pending.\n"
        assert not PendingProviderKeyDeletion.objects.exists()
        assert not (root / row.key_name).exists()
        assert (
            DeveloperProviderKey.objects.get(owner=bob, model_id=MODEL).key_name
            == before
        )
        assert bob_store.status(MODEL)["status"] == "added"
        record(
            "PGKEY-04",
            durable_journal_retry=True,
            session_withdrawn=True,
            other_owner_preserved=True,
        )
    finally:
        RELEASE.set()
        for owner in people:
            if User.objects.filter(pk=owner.pk).exists():
                identity.delete_user(owner.pk)
        ModelApproval.objects.filter(pk=MODEL).delete()
        assert not DeveloperProviderKey.objects.filter(model_id=MODEL).exists()
        assert not PendingProviderKeyDeletion.objects.filter(
            directory=str(root)
        ).exists()
        assert not list(root.iterdir())
        shutil.rmtree(root)
        connections.close_all()
    return {
        "validation": "synthetic",
        "cases": results,
        "fixture_records_and_files_removed": True,
    }


if __name__ == "__main__":
    print(json.dumps(run()))
