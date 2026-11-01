"""One control-plane process that fills, changes or reads a backup-test database.

Run as `python backup_restore_probe.py <action>` with the app's own database
environment (DJANGO_SETTINGS_MODULE=config.settings). It reads one JSON object
from stdin and prints one JSON object. Values are synthetic test data.
"""

import json
import os
import sys
from pathlib import Path

import django

django.setup()

# Host checks keep real file modes; only the container UID chown is skipped,
# as in the developer-key store cases. Container ownership is covered there.
import integrations.gateway.keys as gateway_keys

gateway_keys.os.fchown = lambda *args: None

from accounts.cli_credentials import checksum, current_binding
from accounts.contracts import IdentityError, LoginThrottled
from accounts.models import CliCredentialBinding, User
from accounts.services import DjangoIdentity
from audit.models import AuditRecord
from audit.services import DjangoAuditStore
from common.errors import StorageUnavailable
from data_classes.services import DjangoDataClassStore
from django.db import transaction
from model_registry.catalog import DjangoModelCatalog
from model_registry.developer_keys import DjangoDeveloperKeyStore
from model_registry.fingerprints import fingerprint
from model_registry.key_validation import VerifiedProviderKey
from model_registry.policy import DjangoModelPolicy
from projects.classification import DjangoProjectClasses
from projects.services import DjangoProjectStore

DEVELOPER_PASSWORD = "restore-developer-password"
DEVELOPER_KEY = "synthetic-restore-provider-key"
CLI_TOKEN = "kpc_" + "r" * 43
PROJECT = "6f1c2a52-6a39-4d5e-9d7a-2a3cfb4d9b10"


def resources(revisions):
    """The gateway's definitions, each at the given revision (absent if None)."""
    return [
        {"id": model_id, "revision": revision,
         "value": {"name": model_id, "params": {"model": model_id + "-upstream"}}}
        for model_id, revision in revisions.items()
        if revision is not None
    ]


class Gateway:
    def __init__(self, rows):
        self.rows = rows

    def models(self):
        return 200, {"data": [{"id": row["id"]} for row in self.rows]}

    def resources(self):
        return 200, {"resources": self.rows}


class Validator:
    def __init__(self, digest):
        self.digest = digest

    def __call__(self, owner_id, model_id, key):
        return VerifiedProviderKey(owner_id, model_id, self.digest)

    def require_current(self, verification):
        if verification.definition_fingerprint != self.digest:
            raise ValueError("definition changed")


def services():
    audit = DjangoAuditStore()
    return (
        audit,
        DjangoIdentity(os.environ["FIRST_ADMIN_PASSWORD_FILE"], audit),
        DjangoDataClassStore(audit),
        DjangoModelCatalog(audit),
    )


def actor(user):
    return str(user.pk), user.username


def key_store(owner_id, rows):
    digest = fingerprint("personal-model", rows)
    return DjangoDeveloperKeyStore(
        owner_id, os.environ["PROVIDER_KEY_DIR"], validate_key=Validator(digest)
    ), digest


def populate(request):
    audit, identity, classes, catalog = services()
    rows = resources(request["revisions"])
    for kind in ("settings", "held_requests", "model_answers"):
        audit.set_option(kind, True)
    admin = User.objects.get(username="first-admin")
    by = actor(admin)
    developer = identity.create_user(
        {"username": "restore-developer", "role": "developer",
         "password": DEVELOPER_PASSWORD}
    )
    removed_later = identity.create_user(
        {"username": "removed-later", "role": "admin",
         "password": "removed-later-password"}
    )
    first_admin_token = identity.login(
        "first-admin",
        Path(os.environ["FIRST_ADMIN_PASSWORD_FILE"]).read_text().strip(),
    )
    developer_token = identity.login("restore-developer", DEVELOPER_PASSWORD)
    removed_token = identity.login("removed-later", "removed-later-password")
    classes.set_enabled(True, actor=by)
    for model_id, approved, owned, key_choice in (
        ("keeplane-model", ["Internal", "Confidential"], True, "none"),
        ("customer-model", ["Internal"], False, "none"),
        ("personal-model", ["Internal"], True, "personal"),
    ):
        catalog.approve(
            model_id, approved, fingerprint(model_id, rows), actor=by,
            owned_by_keeplane=owned, key_choice=key_choice,
        )
    DjangoProjectStore().register_use(developer["id"], PROJECT, "Restore project")
    DjangoProjectClasses(audit).assign(PROJECT, "internal", by)
    store, _ = key_store(developer["id"], rows)
    store.put("personal-model", DEVELOPER_KEY)
    owner = User.objects.get(pk=developer["id"])
    with transaction.atomic():
        CliCredentialBinding.objects.create(
            checksum=checksum(CLI_TOKEN), kind="access", owner=owner,
            auth_hash=owner.get_session_auth_hash(),
        )
    audit.record("model_answers", developer["id"], "restore-developer",
                 "Sent a task to keeplane-model for Restore project")
    return {
        "tokens": {"first-admin": first_admin_token,
                   "restore-developer": developer_token,
                   "removed-later": removed_token},
        "removed_later_id": removed_later["id"],
    }


def withdraw(request):
    """What an admin changes after the backup: these must be rechecked after a restore."""
    _, identity, _, catalog = services()
    rows = resources(request["revisions"])
    by = actor(User.objects.get(username="first-admin"))
    catalog.approve("keeplane-model", ["Confidential"],
                    fingerprint("keeplane-model", rows), actor=by,
                    owned_by_keeplane=True)
    catalog.remove("customer-model", actor=by)
    identity.logout(request["tokens"]["restore-developer"])
    identity.delete_user(request["removed_later_id"])
    return {}


def inspect(request):
    audit, identity, classes, catalog = services()
    rows = resources(request["revisions"])
    sessions = {
        name: (identity.session(token) or {}).get("role")
        for name, token in request["tokens"].items()
    }
    developer = User.objects.filter(username="restore-developer").first()
    try:
        signed_in = bool(identity.login("restore-developer", DEVELOPER_PASSWORD))
    except (IdentityError, LoginThrottled):
        signed_in = False
    try:
        store, digest = key_store(developer.pk, rows)
        key = store.resolve("personal-model", expected_definition_fingerprint=digest)
        developer_key = "matches" if key.for_provider() == DEVELOPER_KEY else "different"
    except StorageUnavailable:
        # The store says only that the key is unavailable, never why.
        developer_key = "unavailable"
    policy = DjangoModelPolicy(Gateway(rows))
    approvals = {
        model_id: (catalog.get(model_id) or {}).get("approved_classes")
        for model_id in ("keeplane-model", "customer-model", "personal-model")
    }
    return {
        "accounts": sorted(User.objects.values_list("username", "role")),
        "sessions": sessions,
        "password_sign_in": signed_in,
        "cli_sign_in": current_binding("access", CLI_TOKEN, developer),
        "classes_enabled": classes.enabled(),
        "classes": [row["name"] for row in classes.list()],
        "project_class": DjangoProjectClasses(audit).current(PROJECT)["data_class"],
        "approvals": approvals,
        "eligible": sorted(policy.eligible_model_ids(PROJECT)),
        "developer_key": developer_key,
        "audit": [
            [row.kind, row.actor_name, row.description]
            for row in AuditRecord.objects.order_by("id")
            if row.kind != "break_glass_sign_ins"
        ],
        "break_glass_records": AuditRecord.objects.filter(
            kind="break_glass_sign_ins"
        ).count(),
    }


def future_migration(request):
    """Mark the database as migrated by a newer Keeplane version."""
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    MigrationRecorder(connection).record_applied(
        "model_registry", "9999_from_a_newer_version"
    )
    return {}


def main():
    request = json.loads(sys.stdin.read() or "{}")
    action = {
        "populate": populate, "withdraw": withdraw, "inspect": inspect,
        "future_migration": future_migration,
    }[
        sys.argv[1]
    ]
    print(json.dumps(action(request), sort_keys=True))


if __name__ == "__main__":
    main()
