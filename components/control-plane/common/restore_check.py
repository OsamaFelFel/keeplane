"""Report what a restored Keeplane database holds, without printing secrets.

Used after restoring a backup (manage.py verify_restore). It reads only: the
migration ledger against the migrations this app ships, record counts, whether
unexpired sessions can be read with the configured signing secret, and whether
every registered developer key file is present and readable in PROVIDER_KEY_DIR.
It never prints a password, session key, provider key, key filename or hash.
"""

import logging
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from common.errors import StorageUnavailable

PENDING = (
    "The database is missing migrations this Keeplane version needs. Run "
    "`python manage.py migrate --noinput` (in Kubernetes, the migration Job), "
    "then check again."
)
UNKNOWN = (
    "The database has migrations this Keeplane version doesn't know: the backup "
    "came from a newer version. Restore it with that version or newer."
)
KEYS_NOT_CHECKED = (
    "Developer keys are registered but PROVIDER_KEY_DIR isn't set here. Run this "
    "check in an app copy, where the provider-key volume is mounted."
)
KEYS_MISSING = (
    "Some registered developer key files are missing. Restore the provider-key "
    "volume from the same backup, or ask those developers to add their key again."
)
KEYS_UNREADABLE = (
    "Some developer key files can't be read by this app copy. Restore owner "
    "UID 65532, directory mode 0700 and file mode 0600, then check again."
)


def migration_state():
    executor = MigrationExecutor(connection)
    loader = executor.loader
    pending = [
        f"{migration.app_label}.{migration.name}"
        for migration, backwards in executor.migration_plan(
            loader.graph.leaf_nodes()
        )
        if not backwards
    ]
    known = set(loader.graph.nodes)
    for originals in (m.replaces for m in loader.replacements.values()):
        known.update(originals)
    applied = set(MigrationRecorder(connection).applied_migrations())
    unknown = sorted(
        f"{app}.{name}"
        for app, name in applied - known
        if app in loader.migrated_apps
    )
    return {"applied": len(applied), "pending": pending, "unknown": unknown}


def session_counts(now):
    from accounts.models import User

    unexpired = Session.objects.filter(expire_date__gt=now)
    users = {}
    usable = 0
    # Django logs undecodable session data as suspicious; a changed signing
    # secret makes every row undecodable, which is what this check reports.
    quiet = logging.getLogger("django.security.SuspiciousSession")
    previous, quiet.disabled = quiet.disabled, True
    try:
        for row in unexpired.iterator():
            data = SessionStore().decode(row.session_data)
            owner_id, digest = data.get(SESSION_KEY), data.get(HASH_SESSION_KEY)
            if not owner_id or not digest:
                continue
            if owner_id not in users:
                users[owner_id] = User.objects.filter(
                    pk=owner_id, is_active=True
                ).first()
            user = users[owner_id]
            if user and constant_time_compare(digest, user.get_session_auth_hash()):
                usable += 1
    finally:
        quiet.disabled = previous
    return {"unexpired": unexpired.count(), "usable": usable}


def developer_key_files(directory):
    from model_registry.models import DeveloperProviderKey
    from model_registry.resolved_keys import read_private_key

    names = list(
        DeveloperProviderKey.objects.exclude(key_name="").values_list(
            "key_name", flat=True
        )
    )
    result = {"registered": len(names), "present": 0, "missing": 0, "unreadable": 0}
    if not names:
        return result
    if not directory or not Path(directory).is_absolute():
        result["checked"] = False
        return result
    result["checked"] = True
    for name in names:
        if not (Path(directory) / name).exists():
            result["missing"] += 1
            continue
        try:
            read_private_key(directory, name)
        except StorageUnavailable:
            # Wrong owner or mode, a link, or a malformed file; count it only.
            result["unreadable"] += 1
        else:
            result["present"] += 1
    return result


def record_counts(now):
    from accounts.models import CliCredentialBinding, User
    from audit.models import AuditRecord
    from data_classes.models import DataClass, ProjectClass, Settings
    from model_registry.models import (
        ComplexityLevelChoice,
        ModelApproval,
        PendingProviderKeyDeletion,
        PersonaRule,
    )
    from projects.models import Project

    newest = AuditRecord.objects.order_by("-happened_at").values_list(
        "happened_at", flat=True
    ).first()
    return {
        "accounts": {
            "total": User.objects.count(),
            "active": User.objects.filter(is_active=True).count(),
            "active_admins": User.objects.filter(is_active=True, role="admin").count(),
            "first_admin": User.objects.filter(username="first-admin").exists(),
        },
        "sessions": session_counts(now),
        "cli_sign_ins": CliCredentialBinding.objects.count(),
        "data_classes": {
            "enabled": Settings.objects.filter(pk=1, classes_enabled=True).exists(),
            "classes": DataClass.objects.count(),
            "projects_with_a_class": ProjectClass.objects.count(),
        },
        "projects": Project.objects.count(),
        "model_approvals": ModelApproval.objects.count(),
        "complexity_level_picks": ComplexityLevelChoice.objects.count(),
        "persona_rules": PersonaRule.objects.count(),
        "pending_key_deletions": PendingProviderKeyDeletion.objects.count(),
        "audit_records": {
            "total": AuditRecord.objects.count(),
            "newest": newest.isoformat(timespec="seconds") if newest else None,
        },
    }


def check(provider_key_dir=None):
    """Return the report and whether the database is ready to serve."""
    if provider_key_dir is None:
        provider_key_dir = os.environ.get("PROVIDER_KEY_DIR", "")
    database = settings.DATABASES["default"]
    report = {
        "database": {
            "engine": connection.vendor,
            "name": str(database["NAME"]),
        },
        "migrations": migration_state(),
    }
    problems = []
    if report["migrations"]["unknown"]:
        problems.append(UNKNOWN)
    elif report["migrations"]["pending"]:
        problems.append(PENDING)
    else:
        # Only read records through a schema this app version understands.
        now = timezone.now()
        report["records"] = record_counts(now)
        keys = developer_key_files(provider_key_dir)
        report["developer_key_files"] = keys
        if keys.get("checked") is False:
            problems.append(KEYS_NOT_CHECKED)
        if keys["missing"]:
            problems.append(KEYS_MISSING)
        if keys["unreadable"]:
            problems.append(KEYS_UNREADABLE)
    report["problems"] = problems
    return report, not problems
