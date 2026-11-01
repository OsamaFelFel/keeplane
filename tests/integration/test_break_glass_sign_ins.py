"""Spec 006 ST21 "Break-glass sign-ins" through the sign-in and Audit APIs.

Task 006-01: first use, repeated use, restart, rotation, wrong password and a
storage outage. Every case signs in through Keeplane's real HTTP sign-in in
separate control-plane processes on one fresh database, SQLite and (when
configured) PostgreSQL. The plain-English cases are in
break-glass-sign-in-cases.md.
"""

from datetime import datetime, timezone

import pytest

from tests.integration import test_audit_persistence as persistence

# Reuse the separate-process SQLite and PostgreSQL harness.
database = persistence.database
start_process = persistence.start_process

BREAK_GLASS = "break_glass_sign_ins"
OPTIONAL = {"settings": False, "held_requests": False, "model_answers": False}


@pytest.fixture
def password_file(start_process, tmp_path):
    # start_process writes the mounted first-admin password here.
    return tmp_path / "first-admin-password"


def call(app, method, path, session=None, body=None):
    return app.ask("http", method=method, path=path, session=session, body=body)


def sign_in(app, password, username="first-admin"):
    return call(
        app, "POST", "/api/session", body={"username": username, "password": password}
    )


def sign_ins(app, session, **query):
    query = "&".join(f"{key}={value}" for key, value in query.items())
    answer = call(
        app, "GET", f"/api/audit/records?kind={BREAK_GLASS}&{query}", session=session
    )
    assert answer["status"] == 200, answer
    return answer["body"]


def stored(app):
    return app.ask("stored")


def when(row):
    return datetime.fromisoformat(row["when"])


def test_bgs_01_first_sign_in_after_install_is_recorded(start_process, password_file):
    app = start_process()
    app.ask("migrate")
    assert stored(app)["records"] == 0

    before = datetime.now(timezone.utc).replace(microsecond=0)
    answer = sign_in(app, password_file.read_text().strip())
    after = datetime.now(timezone.utc)
    assert answer["status"] == 200 and answer["session"]
    session = answer["session"]

    options = call(app, "GET", "/api/audit/options", session=session)
    assert options["body"] == {"options": OPTIONAL}
    found = sign_ins(app, session)
    assert found["total"] == 1
    row = found["records"][0]
    assert (row["kind"], row["who"], row["what"]) == (
        BREAK_GLASS,
        "first-admin",
        "Break-glass admin signed in.",
    )
    assert row["when"].endswith("+00:00") and before <= when(row) <= after
    assert call(app, "GET", "/api/audit/records", session=session)["body"]["total"] == 1

    # There is no switch: turning break-glass recording off is refused.
    refused = call(
        app,
        "PUT",
        f"/api/audit/options/{BREAK_GLASS}",
        session=session,
        body={"enabled": False},
    )
    assert refused["status"] == 400
    assert call(app, "GET", "/api/audit/options", session=session)["body"] == {
        "options": OPTIONAL
    }
    assert sign_in(app, password_file.read_text().strip())["status"] == 200
    assert sign_ins(app, session)["total"] == 2


def test_bgs_02_each_repeated_sign_in_gets_its_own_record(start_process, password_file):
    first, second = start_process(), start_process()
    first.ask("migrate")
    password = password_file.read_text().strip()
    sessions = [sign_in(app, password)["session"] for app in (first, second, first)]
    assert all(sessions) and len(set(sessions)) == 3
    # Another admin's sign-in is not a break-glass sign-in.
    created = call(
        first,
        "POST",
        "/api/users",
        session=sessions[0],
        body={"username": "ops-admin", "password": "ops-admin-password-1", "role": "admin"},
    )
    assert created["status"] == 201, created
    assert sign_in(second, "ops-admin-password-1", "ops-admin")["status"] == 200

    for app in (first, second):
        found = sign_ins(app, sessions[-1])
        assert found["total"] == 3
        assert {row["who"] for row in found["records"]} == {"first-admin"}
        ids = [row["id"] for row in found["records"]]
        assert ids == sorted(set(ids), reverse=True)
        for session in sessions:
            identity = call(app, "GET", "/api/identity", session=session)
            assert identity["body"]["role"] == "admin"
    assert stored(first)["records"] == 3


def test_bgs_03_a_wrong_password_signs_nobody_in_and_records_nothing(
    start_process, password_file
):
    app = start_process()
    app.ask("migrate")
    password = password_file.read_text().strip()
    for attempt in ("wrong-password-123", password.upper(), password + " "):
        answer = sign_in(app, attempt)
        assert (answer["status"], answer["session"]) == (401, None)
    assert stored(app) == {"sessions": 0, "records": 0, "record_text": []}

    # The username is not case-sensitive; the record names the account.
    answer = sign_in(app, password, username="First-Admin")
    assert answer["status"] == 200
    found = sign_ins(app, answer["session"])
    assert [row["who"] for row in found["records"]] == ["first-admin"]


def test_bgs_04_a_restart_keeps_sessions_and_records(start_process, password_file):
    app = start_process()
    app.ask("migrate")
    password = password_file.read_text().strip()
    session = sign_in(app, password)["session"]
    sign_in(app, password)
    before = sign_ins(app, session)["records"]
    app.stop()

    restarted = start_process()
    assert call(restarted, "GET", "/api/identity", session=session)["status"] == 200
    assert sign_ins(restarted, session)["records"] == before
    assert sign_in(restarted, password)["status"] == 200
    after = sign_ins(restarted, session)
    assert after["total"] == 3 and after["records"][1:] == before


def test_bgs_05_rotation_ends_old_sessions_and_records_the_new_sign_in(
    start_process, password_file
):
    app = start_process()
    app.ask("migrate")
    old_password = password_file.read_text().strip()
    old_session = sign_in(app, old_password)["session"]
    app.stop()

    new_password = "rotated-break-glass-password-456"
    password_file.write_text(new_password + "\n")
    rotated = start_process()
    # The new process reads the mounted password on its first account call.
    assert sign_in(rotated, old_password)["status"] == 401
    assert call(rotated, "GET", "/api/identity", session=old_session)["status"] == 401
    answer = sign_in(rotated, new_password)
    assert answer["status"] == 200
    found = sign_ins(rotated, answer["session"])
    # The earlier record stays; one new record for the new sign-in only.
    assert found["total"] == 2
    assert {row["who"] for row in found["records"]} == {"first-admin"}
    users = call(rotated, "GET", "/api/users?search=first-admin", session=answer["session"])
    assert users["body"]["total"] == 1


@pytest.mark.parametrize("table", ["audit", "session"])
def test_bgs_06_a_storage_outage_refuses_the_sign_in(
    start_process, password_file, table
):
    app, other = start_process(), start_process()
    app.ask("migrate")
    password = password_file.read_text().strip()
    session = sign_in(app, password)["session"]
    before = stored(app)

    app.ask("outage", table=table, down=True)
    for process in (app, other):
        answer = sign_in(process, password)
        assert answer == {
            "status": 503,
            "body": {"error": "Account storage is unavailable"},
            "session": None,
        }
    # Neither the session nor the record was kept, in either direction.
    assert stored(other) == before

    app.ask("outage", table=table, down=False)
    answer = sign_in(other, password)
    assert answer["status"] == 200
    assert sign_ins(app, session)["total"] == 2
    text = repr(stored(app)["record_text"])
    for secret in (password, session, answer["session"]):
        assert secret not in text
