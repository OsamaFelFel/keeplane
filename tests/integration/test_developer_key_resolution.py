"""Internal owner reads: real files, current Django policy, synthetic keys only."""

import json
import os
import stat
import traceback
from copy import deepcopy
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from accounts.models import User
from common.errors import StorageUnavailable
from django.db import DatabaseError, connection, connections
from model_registry import developer_keys, resolved_keys
from model_registry.developer_keys import DeveloperKeyMissing, DjangoDeveloperKeyStore
from model_registry.fingerprints import fingerprint
from model_registry.key_validation import (
    DjangoProviderKeyValidator,
    VerifiedProviderKey,
)
from model_registry.models import DeveloperProviderKey, ModelApproval

pytestmark = pytest.mark.django_db(transaction=True)
KEY, NEXT = "synthetic-owner-provider-key", "synthetic-replacement-key"


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setattr("integrations.gateway.keys.os.fchown", lambda *args: None)
    resource = {
        "id": "model",
        "revision": 1,
        "value": {"provider": "openAI", "params": {"model": "upstream"}},
    }
    digest = fingerprint("model", [resource])
    ModelApproval.objects.create(
        model_id="model", key_choice="personal", gateway_fingerprint=digest
    )
    gateway = SimpleNamespace(
        request=lambda *args, **kwargs: (200, {"resources": [deepcopy(resource)]})
    )
    current = DjangoProviderKeyValidator(gateway)

    class Validator:
        # Synthetic verification seeds storage; the real current-definition checker
        # is used on every mutation/read. Provider HTTP validation is tested separately.
        def __call__(self, actor, model, key):
            return VerifiedProviderKey(actor, model, digest)

        require_current = current.require_current

    owners = [
        User.objects.create(username=name, role="developer")
        for name in ("alice", "bob")
    ]
    root = tmp_path / "keys"
    stores = [
        DjangoDeveloperKeyStore(owner.pk, str(root), validate_key=Validator())
        for owner in owners
    ]
    stores[0].put("model", KEY)
    path = root / DeveloperProviderKey.objects.get(owner=owners[0]).key_name
    return SimpleNamespace(
        a=stores[0], b=stores[1], root=root, path=path, resource=resource, digest=digest
    )


def resolve(store, digest):
    return store.resolve("model", expected_definition_fingerprint=digest)


def test_owner_isolation_redacted_result_and_next_reads_after_replace_remove(
    owned, monkeypatch
):
    value = resolve(owned.a, owned.digest)
    assert (
        value.for_provider() == KEY and KEY not in repr(value) and KEY not in str(value)
    )
    with pytest.raises(TypeError):
        json.dumps(value)
    with pytest.raises(StorageUnavailable):
        resolve(owned.b, owned.digest)
    owned.b.put("model", NEXT)
    assert resolve(owned.a, owned.digest).for_provider() == KEY
    owned.a.put("model", NEXT)
    assert resolve(owned.a, owned.digest).for_provider() == NEXT
    assert value.for_provider() == KEY  # Returned memory is not a revocable lease.
    with monkeypatch.context() as patch:
        patch.setattr(developer_keys, "remove", lambda *args: False)
        assert owned.a.remove("model")["cleanup_pending"]
    with pytest.raises(StorageUnavailable):
        resolve(owned.a, owned.digest)  # Pending old files are never selected.
    assert resolve(owned.b, owned.digest).for_provider() == NEXT


@pytest.mark.parametrize("state", ["absent", "removed", "unbound"])
def test_only_missing_current_registration_has_a_typed_safe_error(
    owned, state, monkeypatch
):
    if state == "absent":
        store = owned.b
    else:
        store = owned.a
        field = "key_name" if state == "removed" else "validation_fingerprint"
        DeveloperProviderKey.objects.filter(owner_id=store.owner_id).update(
            **{field: ""}
        )

    def unexpected_read(*args):
        raise AssertionError("A missing registration must not read a file")

    monkeypatch.setattr(developer_keys, "read_private_key", unexpected_read)
    with pytest.raises(DeveloperKeyMissing, match="^Provider key is unavailable$"):
        resolve(store, owned.digest)


@pytest.mark.parametrize("value", ["a" * 12, "b" * 512])
def test_private_read_only_files_accept_format_boundaries(owned, value):
    owned.a.put("model", value)
    path = (
        owned.root
        / DeveloperProviderKey.objects.get(owner_id=owned.a.owner_id).key_name
    )
    path.chmod(0o400)
    owned.root.chmod(0o500)
    try:
        assert resolve(owned.a, owned.digest).for_provider() == value
    finally:
        owned.root.chmod(0o700)
        path.chmod(0o600)


@pytest.mark.parametrize(
    "change", ["owner", "approval", "choice", "registry", "binding", "expected"]
)
def test_withdrawn_or_mismatched_state_never_resolves(owned, change):
    digest = owned.digest
    if change == "owner":
        User.objects.filter(pk=owned.a.owner_id).update(is_active=False)
    elif change == "approval":
        ModelApproval.objects.all().delete()
    elif change == "choice":
        ModelApproval.objects.update(key_choice="shared")
    elif change == "registry":
        owned.resource["revision"] += 1
    elif change == "binding":
        DeveloperProviderKey.objects.update(validation_fingerprint="")
    else:
        digest = "b" * 64
    with pytest.raises(StorageUnavailable, match="^Provider key is unavailable$"):
        resolve(owned.a, digest)


@pytest.mark.parametrize(
    "unsafe",
    [
        "symlink",
        "root-symlink",
        "root-symlink-trailing",
        "fifo",
        "directory",
        "hardlink",
        "public-file",
        "public-directory",
        "bad-name",
    ],
)
def test_unsafe_file_or_directory_is_refused(owned, unsafe):
    if unsafe.startswith("root-symlink"):
        moved = owned.root.with_name("moved")
        owned.root.rename(moved)
        owned.root.symlink_to(moved, target_is_directory=True)
        if unsafe == "root-symlink-trailing":
            owned.a.directory += "/"
    elif unsafe == "public-file":
        owned.path.chmod(0o644)
    elif unsafe == "public-directory":
        owned.root.chmod(0o755)
    elif unsafe == "hardlink":
        os.link(owned.path, owned.root / "other-link")
    elif unsafe == "bad-name":
        DeveloperProviderKey.objects.update(key_name="../outside")
    else:
        owned.path.unlink()
        if unsafe == "symlink":
            outside = owned.root.with_name("outside")
            outside.write_text(KEY)
            owned.path.symlink_to(outside)
        elif unsafe == "fifo":
            os.mkfifo(owned.path, 0o600)
        else:
            owned.path.mkdir(mode=0o700)
    with pytest.raises(
        StorageUnavailable, match="^Provider key is unavailable$"
    ) as error:
        resolve(owned.a, owned.digest)
    assert str(owned.root) not in str(error.value) and KEY not in str(error.value)
    assert not isinstance(error.value, DeveloperKeyMissing)


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * 11,
        b"x" * 8192,
        b"synthetic key spaces",
        b"synthetic-key\n",
        b"synthetic-key\x7f",
        b"synthetic-key\xff",
    ],
)
def test_invalid_or_oversized_credentials_are_refused(owned, raw):
    owned.path.write_bytes(raw)
    with pytest.raises(StorageUnavailable, match="^Provider key is unavailable$"):
        resolve(owned.a, owned.digest)


@pytest.mark.parametrize("directory", [False, True])
def test_foreign_ownership_is_refused(owned, monkeypatch, directory):
    original = os.fstat

    def foreign(descriptor):
        info = original(descriptor)
        if stat.S_ISDIR(info.st_mode) == directory:
            return SimpleNamespace(
                st_uid=os.geteuid() + 1,
                st_mode=info.st_mode,
                st_nlink=info.st_nlink,
                st_size=info.st_size,
            )
        return info

    monkeypatch.setattr(resolved_keys.os, "fstat", foreign)
    with pytest.raises(StorageUnavailable):
        resolve(owned.a, owned.digest)


def test_database_failure_after_read_never_exposes_result_or_error_details(
    owned, monkeypatch
):
    def failed():
        raise DatabaseError(KEY + str(owned.path))

    monkeypatch.setattr(connection, "commit", failed)
    with pytest.raises(StorageUnavailable) as error:
        resolve(owned.a, owned.digest)
    rendered = "".join(traceback.format_exception(error.value))
    assert KEY not in rendered and str(owned.path) not in rendered


@pytest.mark.parametrize("mutation", ["replace", "remove"])
def test_sqlite_owner_mutation_waits_for_resolution_transaction(
    owned, monkeypatch, mutation
):
    ready, release, attempted, done = Event(), Event(), Event(), Event()
    outcomes, failures = [], []
    original = developer_keys.read_private_key

    def paused(*args):
        ready.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(developer_keys, "read_private_key", paused)

    def reader():
        try:
            outcomes.append(resolve(owned.a, owned.digest).for_provider())
        except (StorageUnavailable, DatabaseError, AssertionError, OSError) as error:
            failures.append(type(error).__name__)
        finally:
            connections.close_all()

    def writer():
        def observe(execute, sql, params, many, context):
            if sql.startswith("BEGIN IMMEDIATE"):
                attempted.set()
            return execute(sql, params, many, context)

        try:
            with connection.execute_wrapper(observe):
                if mutation == "replace":
                    owned.a.put("model", NEXT)
                else:
                    owned.a.remove("model")
        except (StorageUnavailable, DatabaseError, AssertionError, OSError) as error:
            failures.append(type(error).__name__)
        finally:
            done.set()
            connections.close_all()

    read = Thread(target=reader, daemon=True)
    write = Thread(target=writer, daemon=True)
    read.start()
    try:
        assert ready.wait(5)
        write.start()
        assert attempted.wait(5)
        assert not done.wait(0.05)
    finally:
        release.set()
        read.join(timeout=5)
        if write.ident is not None:
            write.join(timeout=5)
    assert not read.is_alive() and not write.is_alive() and not failures
    assert outcomes == [KEY]
    if mutation == "replace":
        assert resolve(owned.a, owned.digest).for_provider() == NEXT
    else:
        with pytest.raises(StorageUnavailable):
            resolve(owned.a, owned.digest)
