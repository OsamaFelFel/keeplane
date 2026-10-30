"""One control-plane process for Audit persistence checks.

It reads one JSON command per line on stdin and answers with one JSON line, so a
test can keep two processes open on the same database at the same time.
"""

import json
import os
import sys
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PREVIOUS = [("accounts", "0001_initial")]


def migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate(target or executor.loader.graph.leaf_nodes())
    return {"migrated": True}


def write_previous_schema_records(count):
    """Write records the way the schema before the Audit app split stored them."""
    old = MigrationExecutor(connection).loader.project_state(PREVIOUS).apps
    record = old.get_model("accounts", "AuditRecord")
    for index in range(count):
        record.objects.create(
            kind="settings",
            actor_id="subject-legacy",
            actor_name="legacy-admin",
            description=f"Legacy routing change {index:02d}",
        )
    record.objects.create(
        kind="break_glass_sign_ins",
        actor_id="subject-legacy",
        actor_name="first-admin",
        description="Break-glass admin signed in.",
    )
    return {"written": count + 1}


def services():
    from accounts.services import DjangoIdentity
    from audit.services import DjangoAuditStore

    audit = DjangoAuditStore()
    password_file = Path(os.environ["FIRST_ADMIN_PASSWORD_FILE"])
    return audit, DjangoIdentity(password_file, audit), password_file


def handle(command):
    action = command["action"]
    if action == "migrate":
        return migrate([tuple(item) for item in command.get("target", [])])
    if action == "previous_records":
        return write_previous_schema_records(command["count"])
    audit, identity, password_file = services()
    if action == "settings":
        audit.set_option("settings", True)
        for index in range(command["count"]):
            audit.record(
                "settings",
                "subject-1",
                command.get("who", "first-admin"),
                f"{command['prefix']} {index:02d}",
            )
        return {"written": command["count"]}
    if action == "sign_in":
        for _ in range(command["count"]):
            identity.login("first-admin", password_file.read_text().strip())
        return {"signed_in": command["count"]}
    if action == "records":
        return audit.records(**command["query"])
    raise ValueError("Unknown fixture action")


def main():
    for line in sys.stdin:
        try:
            answer = {"ok": True, "result": handle(json.loads(line))}
        except Exception as error:  # noqa: BLE001 - report fixture failures to the test.
            answer = {"ok": False, "error": type(error).__name__ + ": " + str(error)}
        finally:
            connection.close()
        print(json.dumps(answer), flush=True)


if __name__ == "__main__":
    main()
