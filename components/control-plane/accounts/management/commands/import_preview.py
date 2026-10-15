"""One-time import of existing local preview data into the Django schema."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import EditionNote, User, UserOperation
from audit.models import AuditOption, AuditRecord
from data_classes.models import DataClass, ProjectClass, Settings
from model_registry.models import ModelApproval


def rows(path, table):
    if not path or not Path(path).is_file():
        return []
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            return []
        # Table names are the fixed constants below, never request input.
        return [dict(row) for row in db.execute('SELECT * FROM "' + table + '"')]


class Command(BaseCommand):
    help = "Import untouched legacy local databases once; existing Django records are never overwritten."

    def add_arguments(self, parser):
        parser.add_argument("--accounts-file", default="/state/accounts.sqlite3")
        parser.add_argument("--settings-file", default="/state/model-approvals.sqlite3")

    @transaction.atomic
    def handle(self, **options):
        if User.objects.exists():
            return
        accounts = options["accounts_file"]
        state = options["settings_file"]
        users = rows(accounts, "users")
        if not users:
            return
        for row in users:
            encoded = row["password_hash"].replace(
                "scrypt$", "keeplane_preview_scrypt$", 1
            )
            User.objects.create(
                id=row["id"],
                username=row["username"],
                role=row["role"],
                password=encoded,
            )
        for row in rows(accounts, "edition_notes"):
            EditionNote.objects.create(
                user_id=row["user_id"],
                enabled=bool(row["enabled"]),
                seen=bool(row["seen"]),
            )
        for row in rows(accounts, "user_operations"):
            UserOperation.objects.create(
                id=row["id"], actor_id=row["actor_id"], user_id=row["user_id"]
            )
        for row in rows(state, "data_class_settings"):
            Settings.objects.create(id=1, classes_enabled=bool(row["enabled"]))
        for row in rows(state, "data_classes"):
            DataClass.objects.create(**row)
        for row in rows(state, "project_classes"):
            ProjectClass.objects.create(
                project_id=row["project_id"], data_class_id=row["class_id"]
            )
        for row in rows(state, "approved_models"):
            row["approved_classes"] = json.loads(row["approved_classes"])
            row["owned_by_keeplane"] = bool(row["owned_by_keeplane"])
            ModelApproval.objects.create(**row)
        for row in rows(state, "audit_options"):
            AuditOption.objects.create(kind=row["kind"], enabled=bool(row["enabled"]))
        for row in rows(state, "audit_records"):
            when = row.get("happened_at", row.get("when_utc"))
            record = AuditRecord.objects.create(
                kind=row["kind"],
                actor_id=row["actor_id"],
                actor_name=row["actor_name"],
                description=row["description"],
            )
            if when:
                stamp = (
                    datetime.fromtimestamp(when, timezone.utc)
                    if isinstance(when, (int, float))
                    else datetime.fromisoformat(when.replace("Z", "+00:00"))
                )
                AuditRecord.objects.filter(pk=record.pk).update(happened_at=stamp)
        self.stdout.write(
            "Imported existing preview accounts and settings. Sign in again; original files are unchanged."
        )
