"""Withdraw owner references atomically; retain file deletions until completed."""

import os
from pathlib import Path

from common.errors import StorageUnavailable
from django.db import DatabaseError, transaction
from integrations.gateway.keys import KEY_NAME

from .models import DeveloperProviderKey, PendingProviderKeyDeletion


def unlink_managed(directory, name):
    if not Path(directory).is_absolute() or not KEY_NAME.fullmatch(name):
        return False
    try:
        root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except (OSError, ValueError):
        return False
    try:
        try:
            os.unlink(name, dir_fd=root)
        except FileNotFoundError:
            pass
        except OSError:
            return False
        try:
            os.fsync(root)
        except OSError:
            return False
        return True
    finally:
        os.close(root)


def cleanup_pending(*, ids=None, limit=100):
    """A missing file is complete; an unavailable directory stays pending."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Choose a cleanup limit from 1 to 1000")
    rows = PendingProviderKeyDeletion.objects.order_by("pk")
    if ids is not None:
        rows = rows.filter(pk__in=ids)
    selected = list(rows.values_list("pk", flat=True)[:limit])
    removed = 0
    for identifier in selected:
        with transaction.atomic():
            row = (
                PendingProviderKeyDeletion.objects.select_for_update()
                .filter(pk=identifier)
                .first()
            )
            if row and unlink_managed(row.directory, row.key_name):
                row.delete()
                removed += 1
    return {"removed": removed, "pending": rows.count()}


def retire_owner_keys(owner):
    """Caller holds the owner lock and owns the account-removal transaction."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Withdraw owner keys inside the account transaction")
    rows = list(DeveloperProviderKey.objects.select_for_update().filter(owner=owner))
    if not rows:
        return
    directory = os.environ.get("PROVIDER_KEY_DIR", "")
    names = {
        name for row in rows for name in (row.key_name, row.pending_key_name) if name
    }
    if names and (not directory or not Path(directory).is_absolute()):
        raise StorageUnavailable(
            "Provider key storage must be configured before removing this account"
        )
    if any(not KEY_NAME.fullmatch(name) for name in names):
        raise StorageUnavailable("Provider key ownership metadata is unavailable")
    ids = [
        PendingProviderKeyDeletion.objects.create(directory=directory, key_name=name).pk
        for name in sorted(names)
    ]
    DeveloperProviderKey.objects.filter(pk__in=[row.pk for row in rows]).delete()
    if not ids:
        return

    def after_commit():
        try:
            cleanup_pending(ids=ids)
        except DatabaseError:
            # Account removal committed. The durable journal permits retry.
            pass

    transaction.on_commit(after_commit)
