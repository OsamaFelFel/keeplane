"""Opt-in audit records for the identity-protected local preview.

Domain events are written in the same SQLite transaction as local settings.
Request bodies and provider credentials never enter these records.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


KINDS = ("settings", "held_requests", "model_answers")
BREAK_GLASS_KIND = "break_glass_sign_ins"
RECORD_KINDS = (*KINDS, BREAK_GLASS_KIND)


class AuditError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class AuditStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            # SQLite can commit the attached account and audit files atomically
            # only when neither file uses WAL.
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("""CREATE TABLE IF NOT EXISTS audit_options (
                kind TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS audit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                happened_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                description TEXT NOT NULL
            )""")
            connection.execute("""CREATE INDEX IF NOT EXISTS audit_records_kind_id
                ON audit_records (kind, id DESC)""")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def options(self):
        with self._connect() as connection:
            rows = dict(connection.execute("SELECT kind, enabled FROM audit_options"))
        return {kind: bool(rows.get(kind, 0)) for kind in KINDS}

    def set_option(self, kind, enabled):
        if kind not in KINDS or not isinstance(enabled, bool):
            raise AuditError(400, "Choose a valid record kind and on or off")
        with self._connect() as connection:
            connection.execute("""INSERT INTO audit_options (kind, enabled) VALUES (?, ?)
                ON CONFLICT(kind) DO UPDATE SET enabled = excluded.enabled""",
                (kind, int(enabled)))
        return self.options()

    def record_in_transaction(self, connection, kind, actor_id, actor_name, description):
        if kind not in KINDS:
            raise ValueError("Unknown audit record kind")
        enabled = connection.execute("SELECT enabled FROM audit_options WHERE kind = ?", (kind,)).fetchone()
        if not enabled or not enabled[0]:
            return False
        connection.execute("""INSERT INTO audit_records
            (kind, happened_at, actor_id, actor_name, description)
            VALUES (?, ?, ?, ?, ?)""", (kind, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                          actor_id, actor_name, description))
        return True

    def record(self, kind, actor_id, actor_name, description):
        with self._connect() as connection:
            return self.record_in_transaction(connection, kind, actor_id, actor_name, description)

    def record_break_glass_in_transaction(self, connection, actor_id, actor_name):
        """Write an unswitchable event through the sign-in transaction's attachment."""
        connection.execute("""INSERT INTO audit_store.audit_records
            (kind, happened_at, actor_id, actor_name, description)
            VALUES (?, ?, ?, ?, ?)""",
            (BREAK_GLASS_KIND, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             actor_id, actor_name, "Break-glass admin signed in."))

    def records(self, kind="all", search="", page=1, page_size=25):
        if kind != "all" and kind not in RECORD_KINDS:
            raise AuditError(400, "Choose a valid record kind")
        if not isinstance(search, str) or len(search) > 80:
            raise AuditError(400, "Search must be at most 80 characters")
        if not isinstance(page, int) or page < 1 or page > 10000:
            raise AuditError(400, "Page must be between 1 and 10000")
        if not isinstance(page_size, int) or page_size < 1 or page_size > 50:
            raise AuditError(400, "Page size must be between 1 and 50")
        terms = []
        values = []
        if kind != "all":
            terms.append("kind = ?")
            values.append(kind)
        if search:
            literal = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            terms.append("(actor_name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')")
            values.extend(["%" + literal + "%"] * 2)
        where = " WHERE " + " AND ".join(terms) if terms else ""
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM audit_records" + where, values).fetchone()[0]
            rows = connection.execute("""SELECT id, kind, happened_at, actor_name, description
                FROM audit_records""" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                [*values, page_size, (page - 1) * page_size]).fetchall()
        return {"records": [dict(zip(("id", "kind", "when", "who", "what"), row)) for row in rows],
                "total": total, "page": page, "page_size": page_size,
                "has_more": page * page_size < total}
