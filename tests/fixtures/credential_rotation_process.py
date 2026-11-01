"""One long-running control-plane process for the credential rotation cases.

It reads one JSON command per line on stdin and answers with one JSON line, so
a test can rotate a mounted credential file while the process keeps running,
exactly as Kubernetes updates a mounted Secret under a running pod.
"""

import io
import json
import logging
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.management import call_command
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor

ADMIN = ("subject-rotation", "rotation-admin")
LOGGED = []


class Collect(logging.Handler):
    def emit(self, record):
        LOGGED.append(record.getMessage())


logging.getLogger().addHandler(Collect())
logging.getLogger().setLevel(logging.WARNING)


def domain():
    from audit.services import DjangoAuditStore
    from data_classes.services import DjangoDataClassStore
    from model_registry.catalog import DjangoModelCatalog

    audit = DjangoAuditStore()
    return audit, DjangoDataClassStore(audit), DjangoModelCatalog(audit)


def identity():
    from accounts.services import DjangoIdentity
    from audit.services import DjangoAuditStore

    return DjangoIdentity(os.environ["FIRST_ADMIN_PASSWORD_FILE"], DjangoAuditStore())


def set_up(fingerprints):
    """Settings an admin made before the rotation: approvals, classes, records."""
    audit, classes, catalog = domain()
    audit.set_option("settings", True)
    classes.set_enabled(True, ADMIN)
    catalog.approve(
        "keeplane-model", ["Public"], fingerprints["keeplane-model"], ADMIN,
        owned_by_keeplane=True, key_choice="shared",
    )
    catalog.approve(
        "customer-model", [], fingerprints["customer-model"], ADMIN, key_choice="none"
    )
    classes.add({"name": "Finance", "approved_model_ids": ["keeplane-model"]}, None, ADMIN)
    return snapshot()


def snapshot():
    from accounts.models import User
    from audit.models import AuditRecord
    from data_classes.models import DataClass
    from model_registry.models import ModelApproval

    return {
        "approvals": sorted(
            [row.pk, row.key_choice, sorted(row.approved_classes),
             row.gateway_fingerprint, row.owned_by_keeplane]
            for row in ModelApproval.objects.all()
        ),
        "classes": sorted(DataClass.objects.values_list("name", flat=True)),
        "users": sorted(str(pk) for pk in User.objects.values_list("pk", flat=True)),
        "records": AuditRecord.objects.count(),
    }


def database():
    """One request's worth of database work, as the app does per request."""
    from common.errors import StorageUnavailable

    try:
        return {"ok": True, "snapshot": snapshot()}
    except (DatabaseError, StorageUnavailable) as error:
        return {"ok": False, "error": type(error).__name__}


def password_state():
    from common.postgresql.base import rotating_password

    return {"previous_in_use": rotating_password(
        os.environ["KEEPLANE_DATABASE_PASSWORD_FILE"]
    ).previous_in_use}


def gateway():
    from common.api import MODEL_GATEWAY
    from common.web import gateway_runtime

    runtime_status, runtime_body = gateway_runtime()
    models_status, _ = MODEL_GATEWAY.request("/v1/models", timeout=10)
    return {
        "runtime_status": runtime_status,
        "runtime_error": runtime_body.get("error"),
        "models_status": models_status,
    }


def check_credentials():
    out = io.StringIO()
    try:
        call_command("check_credentials", stdout=out)
        code = 0
    except SystemExit as stop:
        code = stop.code
    return {"exit": code, "report": json.loads(out.getvalue())}


def handle(command):
    action = command["action"]
    if action == "migrate":
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        return {"migrated": True}
    if action == "set_up":
        return set_up(command["fingerprints"])
    if action == "database":
        return database()
    if action == "password_state":
        return password_state()
    if action == "sign_in":
        with open(os.environ["FIRST_ADMIN_PASSWORD_FILE"], encoding="utf-8") as source:
            return {"token": identity().login("first-admin", source.read().strip())}
    if action == "session":
        user = identity().session(command["token"])
        return {"username": user["username"] if user else None}
    if action == "gateway":
        return gateway()
    if action == "check_credentials":
        return check_credentials()
    if action == "logged":
        return {"logged": list(LOGGED)}
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
