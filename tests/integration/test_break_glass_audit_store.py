"""Mandatory sign-in records and sessions commit or roll back together."""

from unittest.mock import patch
import pytest
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from accounts.contracts import IdentityError
from accounts.services import DjangoIdentity
from audit.models import AuditRecord
from common.errors import StorageUnavailable


def test_bg_01_first_admin_sign_in_is_always_recorded(domain_services):
    s = domain_services
    token = s.identity.login("first-admin", "first-test-password-123")
    assert s.identity.session(token)["role"] == "admin"
    assert s.audit.records(kind="break_glass_sign_ins")["total"] == 1
    assert s.audit.options() == {
        "settings": False,
        "held_requests": False,
        "model_answers": False,
    }


def test_bg_02_wrong_password_creates_no_session_or_record(domain_services):
    with pytest.raises(IdentityError):
        domain_services.identity.login("first-admin", "wrong-password")
    assert Session.objects.count() == AuditRecord.objects.count() == 0


def test_bg_03_each_successful_sign_in_gets_its_own_record(domain_services):
    s = domain_services
    first = s.identity.login("first-admin", "first-test-password-123")
    second = s.identity.login("first-admin", "first-test-password-123")
    assert first != second
    assert (
        s.audit.records(kind="break_glass_sign_ins", search="first-admin")["total"] == 2
    )
    assert s.audit.records(kind="settings")["total"] == 0


def test_bg_04_rotation_invalidates_existing_sessions(domain_services):
    s = domain_services
    token = s.identity.login("first-admin", "first-test-password-123")
    s.secret.write_text("rotated-first-test-password-456\n")
    rotated = DjangoIdentity(s.secret, s.audit)
    assert rotated.session(token) is None
    assert rotated.session(
        rotated.login("first-admin", "rotated-first-test-password-456")
    )
    assert s.audit.records()["total"] == 2


@pytest.mark.parametrize("failure", ["audit", "session"])
def test_bg_05_failed_write_rolls_back_sign_in(domain_services, failure):
    s = domain_services
    target = (
        "audit.services.AuditRecord.objects.create"
        if failure == "audit"
        else "django.contrib.sessions.backends.db.SessionStore.save"
    )
    with patch(target, side_effect=DatabaseError("fixture storage failure")):
        with pytest.raises(StorageUnavailable):
            s.identity.login("first-admin", "first-test-password-123")
    assert Session.objects.count() == AuditRecord.objects.count() == 0


def test_bg_06_audit_records_contain_no_password_or_session_secret(domain_services):
    s = domain_services
    token = s.identity.login("first-admin", "first-test-password-123")
    record = s.audit.records()["records"][0]
    assert token not in str(record)
    assert "first-test-password-123" not in str(record)
    assert record["when"].endswith("+00:00")
