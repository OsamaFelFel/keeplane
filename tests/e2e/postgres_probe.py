"""Exercise the real Keeplane API and PostgreSQL records in an isolated fixture."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_api.settings")
import django
django.setup()
from django.contrib.sessions.models import Session
from django.db import connection, connections
from django.utils import timezone
from django_api.accounts.models import AuditRecord, LoginBudget, ProjectClass, User
from django_api.persistence import stores
from test_accounts import Browser


STATE = Path("/trial-state")
PASSWORD = Path("/run/secrets/first-admin-password").read_text().strip()
ROTATED = Path("/run/secrets/rotated").read_text().strip()
ORIGINAL_PASSWORD = Path("/run/secrets/original-password").read_text().strip()
A, B = "http://app-a:3000", "http://app-b:3000"


def admin(base=A, password=PASSWORD):
    browser = Browser(base)
    assert browser.fetch("/api/session", {"username": "first-admin", "password": password}, method="POST")[0] == 200
    return browser


def other(browser, base=B):
    # Serving replicas share one public hostname; copy its cookies to the second
    # private fixture address without exposing their values in evidence.
    import copy
    result = Browser(base)
    for cookie in browser.cookies:
        cloned = copy.copy(cookie)
        cloned.domain = base.split("//", 1)[1].split(":", 1)[0] + ".local"
        result.cookies.set_cookie(cloned)
    return result


def save(browser, name):
    # Temporary fixture state is private and deleted by the runner.
    import pickle
    path = STATE / name
    path.write_bytes(pickle.dumps(list(browser.cookies)))
    path.chmod(0o600)


def load(name, base=A):
    import pickle
    result = Browser(base)
    for cookie in pickle.loads((STATE / name).read_bytes()):
        result.cookies.set_cookie(cookie)
    return result


def shared():
    first = admin()
    second = other(first)
    identity_a = first.fetch("/api/identity")[1]
    assert uuid.UUID(identity_a["id"])
    assert second.fetch("/api/identity")[1] == identity_a
    assert second.fetch("/api/users")[0] == 200
    save(first, "stable-session")
    assert second.fetch("/sign-out", method="POST")[0] == 200
    assert first.fetch("/api/identity")[0] == 401
    return {"uuid_identity": True, "shared_session": True, "logout_visible_on_other_copy": True}


def idempotency():
    first = admin()
    body = {"username": "parallel" + secrets.token_hex(4), "password": secrets.token_urlsafe(20),
            "role": "developer", "operation_id": str(uuid.uuid4())}
    clients = [other(first, A if index % 2 == 0 else B) for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        replies = list(executor.map(lambda client: client.fetch("/api/users", body, method="POST"), clients))
    assert [reply[0] for reply in replies] == [201] * 8
    ids = {reply[1]["id"] for reply in replies}
    assert len(ids) == 1 and User.objects.filter(username=body["username"]).count() == 1
    checked = other(first).fetch("/api/user-operations/" + body["operation_id"])
    assert checked[0] == 200 and checked[1]["status"] == "created" and checked[1]["user"]["id"] in ids
    assert other(first).fetch("/api/users", dict(body, password=secrets.token_urlsafe(20)), method="POST")[0] == 409
    role_path = "/api/users/" + next(iter(ids)) + "/role"
    developer = Browser(A)
    assert developer.fetch("/api/session", {"username": body["username"], "password": body["password"]}, method="POST")[0] == 200
    assert developer.fetch("/api/users")[0] == 403
    assert other(first).fetch(role_path, {"role": "admin"}, method="PUT")[0] == 200
    assert developer.fetch("/api/users")[0] == 200
    assert other(first).fetch(role_path, {"role": "developer"}, method="PUT")[0] == 200
    assert developer.fetch("/api/identity")[0] == 401
    first.fetch("/api/users/" + next(iter(ids)), {}, method="DELETE")
    return {"concurrent_requests": 8, "created_users": 1, "conflicting_retry_status": 409, "role_and_revocation_shared": True}


def limits():
    name = "unknown" + secrets.token_hex(5)
    def attempt(index):
        return Browser(A if index % 2 == 0 else B).fetch("/api/session", {"username": name.upper() if index % 2 else name,
                                                                                  "password": "not-the-password"}, method="POST")[0]
    with ThreadPoolExecutor(max_workers=10) as executor:
        statuses = sorted(executor.map(attempt, range(10)))
    assert statuses == [401] * 5 + [429] * 5
    assert User.objects.filter(username__iexact=name).count() == 0
    assert Browser(B).fetch("/api/session", {"username": name, "password": "wrong"}, method="POST")[0] == 429
    LoginBudget.objects.filter(bucket=__import__('local_identity').login_bucket(name)).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert attempt(0) == 401
    return {"attempts": 10, "accepted_password_checks": 5, "throttled": 5, "expired_budget_reopens": True}


def persistence():
    first, second = admin(), admin(B)
    assert first.fetch("/api/data-classes")[1] == {"enabled": False, "classes": []}
    assert first.fetch("/api/audit/options/settings", {"enabled": True}, method="PUT")[0] == 200
    assert first.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")[0] == 200
    classes = second.fetch("/api/data-classes")[1]["classes"]
    assert len(classes) == 3
    status, approval, _ = first.fetch("/api/models/local-fixture/setup", {"key_choice": "none", "approved_classes": ["Public"]}, method="POST")
    assert status == 200
    assert second.fetch("/api/models")[1]["models"][0]["approved_classes"] == ["Public"]
    added = second.fetch("/api/data-classes", {"name": "Restricted", "approved_model_ids": ["local-fixture"]}, method="POST")
    assert added[0] == 201
    path = "/api/data-classes/" + added[1]["id"]
    assert first.fetch(path, {"name": "Sensitive", "approved_model_ids": ["local-fixture"]}, method="PUT")[0] == 200
    assert second.fetch("/api/models")[1]["models"][0]["approved_classes"] == ["Public", "Sensitive"]
    assert second.fetch(path, {}, method="DELETE")[0] == 200
    assert first.fetch("/api/models")[1]["models"][0]["approved_classes"] == ["Public"]
    records = second.fetch("/api/audit/records?kind=settings")[1]
    assert records["total"] >= 5 and all(row["who"] == "first-admin" for row in records["records"])
    assert second.fetch("/api/audit/options/break_glass_sign_ins", {"enabled": False}, method="PUT")[0] == 400
    assert second.fetch("/api/ask", {"model": "local-fixture", "prompt": "Hello"}, method="POST")[0] == 200
    save(first, "durable-session")
    (STATE / "identity-id").write_text(first.fetch("/api/identity")[1]["id"])
    return {"settings_shared": True, "model_approval_shared": True, "class_changes_shared": True,
            "audit_records": records["total"], "mandatory_record_not_switchable": True}


def atomic_failure():
    before_sessions = Session.objects.count()
    before_audit = AuditRecord.objects.count()
    first = admin()
    mode = first.fetch("/api/data-classes")[1]["enabled"]
    before_sessions = Session.objects.count()
    before_audit = AuditRecord.objects.count()
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE accounts_auditrecord ADD CONSTRAINT fixture_reject_audit CHECK (false) NOT VALID")
    try:
        browser = Browser(B)
        denied = browser.fetch("/api/session", {"username": "first-admin", "password": PASSWORD}, method="POST")[0]
        assert denied == 503 and not any(cookie.name == "keeplane_session" for cookie in browser.cookies)
        assert Session.objects.count() == before_sessions and AuditRecord.objects.count() == before_audit
        changed = first.fetch("/api/data-classes/mode", {"enabled": not mode}, method="PUT")[0]
        assert changed == 503 and first.fetch("/api/data-classes")[1]["enabled"] == mode
        approval = first.fetch("/api/models/local-fixture/setup", {"key_choice": "none", "approved_classes": ["Internal"]}, method="POST")[0]
        assert approval == 503 and first.fetch("/api/models")[1]["models"][0]["approved_classes"] == ["Public"]
        renamed = first.fetch("/api/data-classes/public", {"name": "Uncommitted", "approved_model_ids": ["local-fixture"]}, method="PUT")[0]
        assert renamed == 503
        assert first.fetch("/api/models")[1]["models"][0]["approved_classes"] == ["Public"]
        assert first.fetch("/api/data-classes")[1]["classes"][0]["name"] == "Public"
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE accounts_auditrecord DROP CONSTRAINT fixture_reject_audit")
    return {"sign_in_status": 503, "no_session_or_record_committed": True,
            "settings_and_audit_rollback": True, "class_model_and_audit_rollback": True}


def prepare_expiry():
    browser = admin()
    token = next(cookie.value for cookie in browser.cookies if cookie.name == "keeplane_session")
    Session.objects.filter(pk=token).update(expire_date=timezone.now() - timedelta(seconds=1))
    assert other(browser).fetch("/api/identity")[0] == 401
    return {"expired_session_status": 401}


def prepare_rotation():
    browser = admin()
    save(browser, "rotation-session")
    (STATE / "rotation-id").write_text(browser.fetch("/api/identity")[1]["id"])
    refused = [Browser(A if index % 2 else B).fetch("/api/session", {"username": "first-admin", "password": "incorrect"}, method="POST")[0] for index in range(6)]
    assert refused == [401] * 5 + [429]
    return {"prepared": True}


def check_rotation():
    assert load("rotation-session").fetch("/api/identity")[0] == 401
    assert other(load("rotation-session")).fetch("/api/identity")[0] == 401
    assert Browser(A).fetch("/api/session", {"username": "first-admin", "password": ORIGINAL_PASSWORD}, method="POST")[0] == 401
    browser = admin(B, ROTATED)
    assert browser.fetch("/api/identity")[1]["id"] == (STATE / "rotation-id").read_text()
    return {"old_sessions_invalid_on_both_copies": True, "old_password_status": 401, "identity_preserved": True}


def outage():
    browser = load("durable-session")
    assert browser.fetch("/api/identity")[0] == 503
    assert browser.page("/")[0] == 503
    anonymous = Browser(B)
    assert anonymous.fetch("/api/session", {"username": "first-admin", "password": PASSWORD}, method="POST")[0] == 503
    assert not any(cookie.name == "keeplane_session" for cookie in anonymous.cookies)
    assert Browser(A).fetch("/health/ready")[0] == 503
    assert Browser(A).fetch("/health/app")[0] == 200
    return {"identity_status": 503, "protected_page_status": 503, "sign_in_status": 503, "no_new_cookie": True,
            "readiness_status": 503, "liveness_status": 200}


def recovery():
    browser = load("durable-session")
    assert browser.fetch("/api/identity")[1]["id"] == (STATE / "identity-id").read_text()
    assert other(browser).fetch("/api/models")[1]["models"][0]["approved_classes"] == ["Public"]
    assert browser.fetch("/api/data-classes")[1]["enabled"] is True
    assert browser.fetch("/api/audit/records?kind=settings")[1]["total"] >= 5
    assert Browser(A).fetch("/health/ready")[0] == 200
    return {"identity_and_session_preserved": True, "settings_and_approval_preserved": True, "audit_preserved": True}


def versions():
    import psycopg
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version")
        database = cursor.fetchone()[0]
    return {"django": django.get_version(), "psycopg": psycopg.__version__, "libpq": psycopg.pq.version(),
            "driver_implementation": psycopg.pq.__impl__, "postgresql": database,
            "session_engine": __import__('django.conf', fromlist=['settings']).settings.SESSION_ENGINE}


def ascii_usernames():
    browser = admin(B, ROTATED)
    username = "caseI" + secrets.token_hex(4)
    body = {"username": username, "password": secrets.token_urlsafe(20), "role": "developer"}
    status, user, _ = browser.fetch("/api/users", body, method="POST")
    assert status == 201
    assert browser.fetch("/api/users", dict(body, username=username.upper()), method="POST")[0] == 409
    valid = Browser(A)
    assert valid.fetch("/api/session", {"username": username.upper(), "password": body["password"]}, method="POST")[0] == 200
    # Dotless i can uppercase to ASCII I under Unicode database collations.
    # It is never a supported account-name spelling or a new attempt bucket.
    for alias in ("fırst-admin", "first-admın"):
        assert Browser(A).fetch("/api/session", {"username": alias, "password": ROTATED}, method="POST")[0] == 401
        assert not LoginBudget.objects.filter(pk=__import__('local_identity').login_bucket(alias)).exists()
    assert browser.fetch("/api/users/" + user["id"], {}, method="DELETE")[0] == 200
    with connection.cursor() as cursor:
        cursor.execute("SELECT collation_name FROM information_schema.columns WHERE table_name='accounts_user' AND column_name='username'")
        assert cursor.fetchone()[0] == "C"
    return {"ascii_case_login": True, "case_duplicate_status": 409, "unicode_alias_statuses": [401, 401], "comparison_collation": "C"}


def class_invariants():
    browser = admin(B, ROTATED)
    project = ProjectClass.objects.create(project_id=uuid.uuid4().hex, data_class_id="public")
    try:
        rows = browser.fetch("/api/data-classes")[1]["classes"]
        assert next(row for row in rows if row['id'] == 'public')['project_count'] == 1
        assert browser.fetch("/api/data-classes/public", {}, method="DELETE")[0] == 409
    finally:
        project.delete()
    for identifier in ("internal", "confidential"):
        assert browser.fetch("/api/data-classes/" + identifier, {}, method="DELETE")[0] == 200
    assert browser.fetch("/api/data-classes/public", {}, method="DELETE")[0] == 409
    assert browser.fetch("/api/data-classes/mode", {"enabled": False}, method="PUT")[0] == 200
    assert browser.fetch("/api/data-classes", {"name": "Refused", "approved_model_ids": []}, method="POST")[0] == 409
    assert browser.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")[0] == 200
    assert len(browser.fetch("/api/data-classes")[1]["classes"]) == 1
    return {"in_use_class_status": 409, "last_class_status": 409, "disabled_write_status": 409, "definitions_retained": True}


if __name__ == "__main__":
    actions = {"shared": shared, "idempotency": idempotency, "limits": limits,
               "persistence": persistence, "atomic-failure": atomic_failure, "expiry": prepare_expiry,
               "prepare-rotation": prepare_rotation, "rotation": check_rotation,
               "outage": outage, "recovery": recovery, "versions": versions,
               "ascii-usernames": ascii_usernames, "class-invariants": class_invariants}
    print(json.dumps(actions[sys.argv[1]]()))
    connections.close_all()
