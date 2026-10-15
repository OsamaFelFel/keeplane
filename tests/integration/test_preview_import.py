"""Existing preview credentials and settings survive the move to Django."""

import hashlib
import sqlite3
import uuid
import pytest
from django.core.management import call_command
from accounts.models import User
from model_registry.models import ModelApproval


@pytest.mark.django_db
def test_preview_import_preserves_sources_and_upgrades_passwords(tmp_path):
    accounts, state = tmp_path / "accounts.sqlite3", tmp_path / "settings.sqlite3"
    salt = b"fixture-salt-1234"
    password = "existing-preview-password-123"
    encoded = (
        "scrypt$16384$5$"
        + salt.hex()
        + "$"
        + hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=5).hex()
    )
    identifier = str(uuid.uuid4())
    with sqlite3.connect(accounts) as db:
        db.execute("CREATE TABLE users(id,username,password_hash,role)")
        db.execute(
            "INSERT INTO users VALUES(?,?,?,?)",
            (identifier, "existing-developer", encoded, "developer"),
        )
    with sqlite3.connect(state) as db:
        db.execute(
            "CREATE TABLE approved_models(model_id,key_choice,approved_classes,gateway_fingerprint,owned_by_keeplane)"
        )
        db.execute(
            "INSERT INTO approved_models VALUES('existing-model','none','[]','definition-one',1)"
        )
    original = [path.read_bytes() for path in (accounts, state)]
    call_command(
        "import_preview", accounts_file=str(accounts), settings_file=str(state)
    )
    user = User.objects.get(pk=identifier)
    assert user.role == "developer" and user.check_password(password)
    user.refresh_from_db()
    assert user.password.startswith("pbkdf2_sha256$")
    assert ModelApproval.objects.get(pk="existing-model").owned_by_keeplane is True
    user.role = "admin"
    user.save()
    call_command(
        "import_preview", accounts_file=str(accounts), settings_file=str(state)
    )
    user.refresh_from_db()
    assert user.role == "admin"
    assert original == [path.read_bytes() for path in (accounts, state)]
