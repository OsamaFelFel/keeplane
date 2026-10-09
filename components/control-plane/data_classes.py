"""Persistent data-class settings for the protected local trial."""

import json
import sqlite3
import uuid
from pathlib import Path


STARTERS = (("public", "Public"), ("internal", "Internal"),
            ("confidential", "Confidential"))


class DataClassError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class DataClassStore:
    def __init__(self, path, audit=None):
        self.path = Path(path)
        self.audit = audit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS data_classes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                position INTEGER NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS project_classes (
                project_id TEXT PRIMARY KEY,
                class_id TEXT NOT NULL
            )""")
            if not connection.execute("SELECT 1 FROM data_classes LIMIT 1").fetchone():
                connection.executemany(
                    "INSERT INTO data_classes (id, name, position) VALUES (?, ?, ?)",
                    [(identifier, name, position) for position, (identifier, name) in enumerate(STARTERS)])

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _rows(self, connection):
        return connection.execute(
            "SELECT id, name FROM data_classes ORDER BY position, name").fetchall()

    def _approvals(self, connection):
        return [(model_id, json.loads(classes)) for model_id, classes in
                connection.execute("SELECT model_id, approved_classes FROM approved_models").fetchall()]

    def list(self, effective_model_ids=None):
        with self._connect() as connection:
            approvals = self._approvals(connection)
            rows = self._rows(connection)
            counts = dict(connection.execute(
                "SELECT class_id, COUNT(*) FROM project_classes GROUP BY class_id").fetchall())
        return [{"id": identifier, "name": name,
                 "approved_model_ids": [model_id for model_id, classes in approvals if name in classes
                                        and (effective_model_ids is None or model_id in effective_model_ids)],
                 "project_count": counts.get(identifier, 0)} for identifier, name in rows]

    def _validate(self, connection, name, model_ids, current_id=None, effective_model_ids=None):
        if not isinstance(name, str):
            raise DataClassError(400, "Enter a class name")
        name = name.strip()
        if not 2 <= len(name) <= 80 or any(ord(character) < 32 for character in name):
            raise DataClassError(400, "Class name must be 2–80 printable characters")
        if any(other_name.casefold() == name.casefold() and identifier != current_id
               for identifier, other_name in self._rows(connection)):
            raise DataClassError(409, "A class with this name already exists")
        if not isinstance(model_ids, list) or any(not isinstance(item, str) for item in model_ids) or \
                len(set(model_ids)) != len(model_ids):
            raise DataClassError(400, "Choose valid approved models")
        known = {model_id for model_id, _ in self._approvals(connection)}
        if not set(model_ids).issubset(known) or \
                (effective_model_ids is not None and not set(model_ids).issubset(effective_model_ids)):
            raise DataClassError(400, "Choose models already set up in Keeplane")
        return name

    def _set_models(self, connection, old_name, new_name, model_ids):
        chosen = set(model_ids)
        for model_id, classes in self._approvals(connection):
            revised = [item for item in classes if item != old_name]
            if model_id in chosen:
                revised.append(new_name)
            if revised:
                connection.execute("UPDATE approved_models SET approved_classes = ? WHERE model_id = ?",
                                   (json.dumps(revised), model_id))
            else:
                connection.execute("DELETE FROM approved_models WHERE model_id = ?", (model_id,))

    def add(self, body, effective_model_ids=None, actor=None):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            name = self._validate(connection, body.get("name"), body.get("approved_model_ids"),
                                  effective_model_ids=effective_model_ids)
            identifier = uuid.uuid4().hex
            position = connection.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM data_classes").fetchone()[0]
            connection.execute("INSERT INTO data_classes (id, name, position) VALUES (?, ?, ?)",
                               (identifier, name, position))
            self._set_models(connection, None, name, body["approved_model_ids"])
            if self.audit and actor:
                self.audit.record_in_transaction(connection, "settings", *actor,
                    f"Added data class {name}; approved models: {', '.join(body['approved_model_ids']) or 'none'}")
        return {"id": identifier, "name": name,
                "approved_model_ids": body["approved_model_ids"], "project_count": 0}

    def edit(self, identifier, body, effective_model_ids=None, actor=None):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT name FROM data_classes WHERE id = ?", (identifier,)).fetchone()
            if row is None:
                raise DataClassError(404, "Class not found")
            name = self._validate(connection, body.get("name"), body.get("approved_model_ids"),
                                  identifier, effective_model_ids)
            previous_models = {model_id for model_id, classes in self._approvals(connection)
                               if row[0] in classes}
            connection.execute("UPDATE data_classes SET name = ? WHERE id = ?", (name, identifier))
            self._set_models(connection, row[0], name, body["approved_model_ids"])
            if self.audit and actor and (name != row[0] or set(body["approved_model_ids"]) != previous_models):
                self.audit.record_in_transaction(connection, "settings", *actor,
                    f"Changed data class {row[0]} to {name}; approved models: {', '.join(body['approved_model_ids']) or 'none'}")
            count = connection.execute("SELECT COUNT(*) FROM project_classes WHERE class_id = ?",
                                       (identifier,)).fetchone()[0]
        return {"id": identifier, "name": name,
                "approved_model_ids": body["approved_model_ids"], "project_count": count}

    def remove(self, identifier, actor=None):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT name FROM data_classes WHERE id = ?", (identifier,)).fetchone()
            if row is None:
                raise DataClassError(404, "Class not found")
            if connection.execute("SELECT 1 FROM project_classes WHERE class_id = ? LIMIT 1",
                                  (identifier,)).fetchone():
                raise DataClassError(409, "Projects still use this class")
            if connection.execute("SELECT COUNT(*) FROM data_classes").fetchone()[0] == 1:
                raise DataClassError(409, "Keep at least one data class")
            for model_id, classes in self._approvals(connection):
                if row[0] in classes:
                    revised = [item for item in classes if item != row[0]]
                    if revised:
                        connection.execute("UPDATE approved_models SET approved_classes = ? WHERE model_id = ?",
                                           (json.dumps(revised), model_id))
                    else:
                        connection.execute("DELETE FROM approved_models WHERE model_id = ?", (model_id,))
            connection.execute("DELETE FROM data_classes WHERE id = ?", (identifier,))
            if self.audit and actor:
                self.audit.record_in_transaction(connection, "settings", *actor,
                                                 f"Removed data class {row[0]}")
        return {"removed": True}
