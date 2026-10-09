"""Local trial catalog for models that Keeplane has explicitly approved.

The gateway may have unrelated models. Only entries here can receive work
through the identity-enabled Keeplane preview. Production storage is separate.
"""

import json
import hashlib
import sqlite3
from pathlib import Path


def fingerprint(model_id, resources, file_owned_config=None):
    """Bind approval to the gateway definition and its update revision."""
    entry = next((item for item in resources if item.get("id") == model_id), None)
    if entry is None:
        if model_id == "local-fixture" and file_owned_config:
            try:
                return "file-owned:" + hashlib.sha256(Path(file_owned_config).read_bytes()).hexdigest()
            except OSError:
                return None
        return None
    revision = entry.get("revision")
    if not isinstance(revision, int) or revision < 1:
        return None
    canonical = json.dumps({"value": entry.get("value", {}), "revision": revision},
                           sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


class ModelCatalog:
    def __init__(self, path, audit=None):
        self.path = Path(path)
        self.audit = audit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS approved_models (
                model_id TEXT PRIMARY KEY,
                key_choice TEXT NOT NULL,
                approved_classes TEXT NOT NULL,
                gateway_fingerprint TEXT NOT NULL,
                owned_by_keeplane INTEGER NOT NULL DEFAULT 0
            )""")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def get(self, model_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT key_choice, approved_classes, gateway_fingerprint, owned_by_keeplane "
                "FROM approved_models WHERE model_id = ?",
                (model_id,)).fetchone()
        if row is None:
            return None
        classes = json.loads(row[1])
        if not classes:
            return None
        return {"key_choice": row[0], "approved_classes": classes,
                "gateway_fingerprint": row[2], "owned_by_keeplane": bool(row[3])}

    def approve(self, model_id, classes, gateway_fingerprint, actor=None,
                owned_by_keeplane=False, key_choice="none"):
        if key_choice not in ("none", "shared"):
            raise ValueError("Choose a supported provider key option")
        if not isinstance(classes, list) or not classes or \
                any(not isinstance(item, str) for item in classes) or \
                len(classes) != len(set(classes)):
            raise ValueError("Choose one or more valid data classes")
        if not gateway_fingerprint:
            raise ValueError("The gateway model definition could not be verified")
        with self._connect() as connection:
            known = [row[0] for row in connection.execute(
                "SELECT name FROM data_classes ORDER BY position, name").fetchall()]
            if not set(classes).issubset(known):
                raise ValueError("Choose one or more valid data classes")
            ordered = [name for name in known if name in classes]
            previous = connection.execute("""SELECT approved_classes, gateway_fingerprint, owned_by_keeplane, key_choice
                FROM approved_models WHERE model_id = ?""", (model_id,)).fetchone()
            connection.execute("""INSERT INTO approved_models
                (model_id, key_choice, approved_classes, gateway_fingerprint, owned_by_keeplane)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                  key_choice = excluded.key_choice,
                  approved_classes = excluded.approved_classes,
                  gateway_fingerprint = excluded.gateway_fingerprint,
                  owned_by_keeplane = excluded.owned_by_keeplane""",
                (model_id, key_choice, json.dumps(ordered), gateway_fingerprint, int(owned_by_keeplane)))
            if self.audit and actor and (not previous or json.loads(previous[0]) != ordered or
                                         previous[1] != gateway_fingerprint or
                                         bool(previous[2]) != bool(owned_by_keeplane) or
                                         previous[3] != key_choice):
                self.audit.record_in_transaction(connection, "settings", *actor,
                    f"Set up model {model_id}; key choice: {key_choice}; approved classes: {', '.join(ordered)}")
        return {"model_id": model_id, "key_choice": key_choice, "approved_classes": ordered,
                "owned_by_keeplane": bool(owned_by_keeplane)}

    def remove(self, model_id, actor=None, gateway_removed=False):
        with self._connect() as connection:
            removed = bool(connection.execute("DELETE FROM approved_models WHERE model_id = ?",
                                              (model_id,)).rowcount)
            if removed and self.audit and actor:
                self.audit.record_in_transaction(connection, "settings", *actor,
                    f"Removed {'model' if gateway_removed else 'Keeplane setup for model'} {model_id}"
                    + (" from the gateway" if gateway_removed else ""))
            return removed
