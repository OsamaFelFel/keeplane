"""Verify that the previous Django schema upgrades without losing records."""

from datetime import timedelta
import uuid

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


def check_upgrade():
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    previous = [("accounts", "0001_initial")]
    executor.migrate(previous)
    old = executor.loader.project_state(previous).apps
    identifier, operation = uuid.uuid4(), uuid.uuid4()
    password = "migration-fixture-password"
    user = old.get_model("accounts", "User").objects.create(
        id=identifier,
        username="migration-developer",
        role="developer",
        password=make_password(password),
    )
    old.get_model("accounts", "EditionNote").objects.create(
        user=user, enabled=False, seen=True
    )
    old.get_model("accounts", "UserOperation").objects.create(
        id=operation, actor_id=identifier, user=user
    )
    old.get_model("accounts", "LoginBudget").objects.create(
        bucket="migration-bucket",
        attempts=2,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    session = old.get_model("sessions", "Session").objects.create(
        session_key="migration-session",
        session_data="preserved-session",
        expire_date=timezone.now() + timedelta(days=1),
    )
    old.get_model("accounts", "SessionOwner").objects.create(session=session, user=user)
    old.get_model("accounts", "DataClass").objects.create(
        id="migration-class", name="Migration", position=90
    )
    old.get_model("accounts", "ProjectClass").objects.create(
        project_id="migration-project", data_class_id="migration-class"
    )
    old.get_model("accounts", "Settings").objects.create(id=1, classes_enabled=True)
    old.get_model("accounts", "ModelApproval").objects.create(
        model_id="migration-model",
        key_choice="none",
        approved_classes=["Migration"],
        gateway_fingerprint="preserved-definition",
        owned_by_keeplane=True,
    )
    old.get_model("accounts", "AuditOption").objects.create(
        kind="migration", enabled=True
    )
    record = old.get_model("accounts", "AuditRecord").objects.create(
        kind="migration",
        actor_id=str(identifier),
        actor_name=user.username,
        description="Preserved historical record",
    )
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        from accounts.models import (
            EditionNote,
            LoginBudget,
            SessionOwner,
            User,
            UserOperation,
        )
        from audit.models import AuditOption, AuditRecord
        from data_classes.models import DataClass, ProjectClass, Settings
        from model_registry.models import ModelApproval
        from django.contrib.sessions.models import Session

        migrated_user = User.objects.get(pk=identifier)
        assert migrated_user.role == "developer" and migrated_user.check_password(
            password
        )
        note = EditionNote.objects.get(user_id=identifier)
        assert not note.enabled and note.seen
        assert UserOperation.objects.get(pk=operation).user_id == identifier
        assert LoginBudget.objects.get(pk="migration-bucket").attempts == 2
        assert Session.objects.get(pk=session.pk).session_data == "preserved-session"
        assert SessionOwner.objects.get(pk=session.pk).user_id == identifier
        assert DataClass.objects.get(pk="migration-class").name == "Migration"
        assert (
            ProjectClass.objects.get(pk="migration-project").data_class_id
            == "migration-class"
        )
        assert Settings.objects.get(pk=1).classes_enabled
        approval = ModelApproval.objects.get(pk="migration-model")
        assert approval.approved_classes == ["Migration"] and approval.owned_by_keeplane
        assert approval.gateway_fingerprint == "preserved-definition"
        assert AuditOption.objects.get(pk="migration").enabled
        migrated_record = AuditRecord.objects.get(pk=record.pk)
        assert migrated_record.description == record.description
        assert migrated_record.happened_at == record.happened_at

        # Leave the disposable API fixture empty for its normal bootstrap.
        Session.objects.filter(pk=session.pk).delete()
        migrated_user.delete()
        LoginBudget.objects.filter(pk="migration-bucket").delete()
        ProjectClass.objects.filter(pk="migration-project").delete()
        DataClass.objects.filter(pk="migration-class").delete()
        Settings.objects.filter(pk=1).delete()
        approval.delete()
        AuditOption.objects.filter(pk="migration").delete()
        migrated_record.delete()
        return {"previous_schema_upgraded": True, "record_types_preserved": 12}
    finally:
        MigrationExecutor(connection).migrate(current)


if __name__ == "__main__":
    import json
    import os
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    print(json.dumps(check_upgrade()))
