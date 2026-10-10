"""Isolated transaction and failure checks for mandatory break-glass records."""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))
from audit import AuditStore
from local_identity import IdentityError, LocalIdentity


def count(database, table):
    with sqlite3.connect(database) as connection:
        return connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def journal_mode(database):
    with sqlite3.connect(database) as connection:
        return connection.execute("PRAGMA journal_mode").fetchone()[0]


def main():
    cases = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    with tempfile.TemporaryDirectory(prefix="keeplane-break-glass-") as temp:
        root = Path(temp)
        accounts = root / "accounts.sqlite3"
        audit_path = root / "audit.sqlite3"
        secret = root / "first-admin-password"
        password = "first-test-password-123"
        secret.write_text(password + "\n")
        audit = AuditStore(audit_path)
        identity = LocalIdentity(accounts, secret, audit)

        token = identity.login("first-admin", password)
        first = audit.records(kind="break_glass_sign_ins")
        record("BG-01", identity.session(token)["role"] == "admin" and first["total"] == 1 and
               first["records"][0]["who"] == "first-admin" and
               first["records"][0]["when"].endswith("+00:00") and
               journal_mode(accounts) == journal_mode(audit_path) == "delete" and
               audit.options() == {"settings": False, "held_requests": False,
                                   "model_answers": False},
               {"sessions": count(accounts, "sessions"), "records": first["total"],
                "account_journal": journal_mode(accounts), "audit_journal": journal_mode(audit_path)})

        wrong_status = None
        try:
            identity.login("first-admin", "wrong-password")
        except IdentityError as error:
            wrong_status = error.status
        record("BG-02", wrong_status == 401 and audit.records(kind="break_glass_sign_ins")["total"] == 1,
               {"wrong_password_status": wrong_status, "records": audit.records(kind="break_glass_sign_ins")["total"]})

        second = identity.login("first-admin", password)
        filtered = audit.records(kind="break_glass_sign_ins", search="first-admin")
        record("BG-03", second != token and identity.session(second) is not None and
               filtered["total"] == 2 and audit.records(kind="settings")["total"] == 0,
               {"filtered_records": filtered["total"]})

        secret.write_text("new-test-password-456\n")
        identity = LocalIdentity(accounts, secret, audit)
        old_refused = None
        try:
            identity.login("first-admin", password)
        except IdentityError as error:
            old_refused = error.status
        new_token = identity.login("first-admin", "new-test-password-456")
        record("BG-04", identity.session(token) is None and identity.session(second) is None and
               old_refused == 401 and identity.session(new_token) is not None and
               audit.records(kind="break_glass_sign_ins")["total"] == 3,
               {"old_password_status": old_refused,
                "records_after_rotation": audit.records(kind="break_glass_sign_ins")["total"]})

        with sqlite3.connect(audit_path) as connection:
            connection.execute("""CREATE TRIGGER refuse_sign_in BEFORE INSERT ON audit_records
                WHEN NEW.kind='break_glass_sign_ins'
                BEGIN SELECT RAISE(ABORT, 'audit store unavailable'); END""")
        before_sessions = count(accounts, "sessions")
        before_records = audit.records(kind="break_glass_sign_ins")["total"]
        unavailable_status = None
        try:
            identity.login("first-admin", "new-test-password-456")
        except IdentityError as error:
            unavailable_status = error.status
        with sqlite3.connect(audit_path) as connection:
            connection.execute("DROP TRIGGER refuse_sign_in")
        with sqlite3.connect(accounts) as connection:
            connection.execute("""CREATE TRIGGER refuse_session BEFORE INSERT ON sessions
                BEGIN SELECT RAISE(ABORT, 'session store unavailable'); END""")
        session_failure_status = None
        try:
            identity.login("first-admin", "new-test-password-456")
        except IdentityError as error:
            session_failure_status = error.status
        record("BG-05", unavailable_status == session_failure_status == 503 and
               count(accounts, "sessions") == before_sessions and
               audit.records(kind="break_glass_sign_ins")["total"] == before_records,
               {"audit_failure_status": unavailable_status,
                "session_failure_status": session_failure_status,
                "sessions_added": count(accounts, "sessions") - before_sessions,
                "records_added": audit.records(kind="break_glass_sign_ins")["total"] - before_records})
        with sqlite3.connect(accounts) as connection:
            connection.execute("DROP TRIGGER refuse_session")

        recovered = identity.login("first-admin", "new-test-password-456")
        entries = audit.records(kind="break_glass_sign_ins", search="first-admin")["records"]
        audit_text = " ".join(str(value) for entry in entries for value in entry.values())
        secrets_in_records = any(value in audit_text for value in
                                 (password, "new-test-password-456", token, second, recovered))
        record("BG-06", identity.session(recovered) is not None and len(entries) == 4 and
               not secrets_in_records,
               {"records_after_repair": len(entries), "secrets_in_records": secrets_in_records})

    print(json.dumps({"results": cases}))
    if any(case["verdict"] != "pass" for case in cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
