"""Local account store for the Open Source Docker preview.

Production password policy, recovery, and deployment remain release gates.
"""

from contextlib import contextmanager
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path


SESSION_SECONDS = 8 * 60 * 60
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{3,64}\Z")


class IdentityError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def pagination(query):
    try:
        page = int(query.get("page", ["1"])[0])
        size = int(query.get("page_size", ["20"])[0])
    except ValueError:
        raise IdentityError(400, "Page and page size must be numbers")
    if page < 1 or page > 10000 or size < 1 or size > 50:
        raise IdentityError(400, "Page must be positive and page size at most 50")
    return page, size


def password_hash(password, salt=None, parallelism=5):
    salt = salt or secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8,
                          p=parallelism)
    return f"scrypt$16384${parallelism}${salt.hex()}${value.hex()}"


DUMMY_HASH = password_hash("not-a-real-account", b"KeeplaneDummy123")


class LocalIdentity:
    def __init__(self, database, first_admin_password_file):
        self.database = database
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL
                        CHECK (role IN ('admin', 'developer'))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edition_notes (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                    seen INTEGER NOT NULL DEFAULT 0 CHECK (seen IN (0, 1))
                );
            """)
            if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                password = Path(first_admin_password_file).read_text().strip()
                if len(password) < 12:
                    raise RuntimeError("First-admin password must be at least 12 characters")
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                           (str(uuid.uuid4()), "first-admin", password_hash(password), "admin"))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            raise IdentityError(401, "Invalid username or password")
        with self.connect() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            stored = user["password_hash"] if user else DUMMY_HASH
            if not stored.startswith("scrypt$"):
                raise IdentityError(503, "Account hash settings need review")
            _, cost, parallelism, salt, expected = stored.split("$", 4)
            if cost != "16384" or parallelism != "5":
                raise IdentityError(503, "Account hash settings need review")
            actual = password_hash(password, bytes.fromhex(salt)).rsplit("$", 1)[1]
            if not user or not hmac.compare_digest(actual, expected):
                raise IdentityError(401, "Invalid username or password")
            if user["role"] != "admin":
                raise IdentityError(403, "This account cannot use the admin UI")
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (digest, user["id"], int(time.time()) + SESSION_SECONDS))
            return token

    def session(self, token):
        if not token or len(token) > 200:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("""SELECT users.id, users.username, users.role FROM sessions
                                JOIN users ON users.id=sessions.user_id
                                WHERE token_hash=? AND expires_at>?""",
                             (digest, int(time.time()))).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        if token:
            with self.connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?",
                           (hashlib.sha256(token.encode()).hexdigest(),))

    def users(self, query):
        page, size = pagination(query)
        search = query.get("search", [""])[0].strip()
        if len(search) > 80:
            raise IdentityError(400, "Search is too long")
        with self.connect() as db:
            found = db.execute("""SELECT id, username, role FROM users
                                  WHERE instr(lower(username), lower(?)) > 0
                                  ORDER BY lower(username), id LIMIT ? OFFSET ?""",
                               (search, size + 1, (page - 1) * size)).fetchall()
        return {"users": [dict(row) for row in found[:size]], "page": page,
                "page_size": size, "has_more": len(found) > size}

    def create_user(self, body):
        username, password, role = body.get("username"), body.get("password"), body.get("role")
        if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
            raise IdentityError(400, "Username must be 3–64 letters, numbers, dots, dashes or underscores")
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise IdentityError(400, "Password must be 12–256 characters")
        if role not in ("admin", "developer"):
            raise IdentityError(400, "Choose admin or developer")
        user = {"id": str(uuid.uuid4()), "username": username, "role": role}
        try:
            with self.connect() as db:
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                           (user["id"], username, password_hash(password), role))
        except sqlite3.IntegrityError:
            raise IdentityError(409, "That name already exists")
        return user

    def delete_user(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise IdentityError(404, "Account not found")
            if row["username"] == "first-admin":
                raise IdentityError(403, "The first admin cannot be removed")
            db.execute("DELETE FROM users WHERE id=?", (user_id,))
        return {"removed": True}

    def edition_note(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT enabled FROM edition_notes WHERE user_id=?",
                             (user_id,)).fetchone()
        return {"enabled": bool(row["enabled"]) if row else True}

    def set_edition_note(self, user_id, enabled):
        if type(enabled) is not bool:
            raise IdentityError(400, "Choose whether to show the Enterprise note")
        with self.connect() as db:
            db.execute("""INSERT INTO edition_notes (user_id, enabled, seen) VALUES (?, ?, 0)
                          ON CONFLICT(user_id) DO UPDATE SET
                            enabled=excluded.enabled,
                            seen=CASE WHEN edition_notes.enabled=0 AND excluded.enabled=1
                                      THEN 0 ELSE edition_notes.seen END""",
                       (user_id, int(enabled)))
        return {"enabled": enabled}

    def consume_edition_note(self, user_id):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO edition_notes (user_id) VALUES (?)", (user_id,))
            changed = db.execute("""UPDATE edition_notes SET seen=1
                                    WHERE user_id=? AND enabled=1 AND seen=0""",
                                 (user_id,)).rowcount
        return {"show": changed == 1}
