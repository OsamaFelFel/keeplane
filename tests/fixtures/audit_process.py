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
ADMIN = ("subject-settings", "settings-admin")
FIRST = "a" * 64
SECOND = "b" * 64


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


def domain():
    from audit.services import DjangoAuditStore
    from data_classes.services import DjangoDataClassStore
    from model_registry.catalog import DjangoModelCatalog

    audit = DjangoAuditStore()
    return audit, DjangoDataClassStore(audit), DjangoModelCatalog(audit)


def class_id(classes, name):
    return next(row["id"] for row in classes.list() if row["name"] == name)


def settings_changes():
    """Every admin change to a model or a data class, through the real stores.

    Repeated identical requests are included; they change nothing and must not
    add a record.
    """
    _, classes, catalog = domain()
    classes.set_enabled(True, ADMIN)
    classes.set_enabled(True, ADMIN)
    shared = {"owned_by_keeplane": True, "key_choice": "shared"}
    catalog.approve("alpha", ["Public"], FIRST, ADMIN, **shared)
    catalog.approve("alpha", ["Public"], FIRST, ADMIN, **shared)
    catalog.approve("alpha", ["Public", "Internal"], FIRST, ADMIN, **shared)
    catalog.approve(
        "alpha",
        ["Public", "Internal"],
        SECOND,
        ADMIN,
        shared_key_replaced=True,
        **shared,
    )
    catalog.approve(
        "alpha",
        ["Public", "Internal"],
        SECOND,
        ADMIN,
        owned_by_keeplane=True,
        key_choice="personal",
    )
    catalog.approve("beta", [], FIRST, ADMIN)
    catalog.approve("beta", [], SECOND, ADMIN)
    added = classes.add(
        {"name": "Finance", "approved_model_ids": ["alpha"]}, None, ADMIN
    )
    classes.edit(
        added["id"], {"name": "Finance", "approved_model_ids": ["alpha"]}, None, ADMIN
    )
    classes.edit(
        added["id"], {"name": "Finance team", "approved_model_ids": []}, None, ADMIN
    )
    classes.edit(
        added["id"],
        {"name": "Finance team", "approved_model_ids": ["alpha", "beta"]},
        None,
        ADMIN,
    )
    classes.remove(added["id"], ADMIN)
    catalog.remove("beta", ADMIN, remove_from_gateway=lambda: (200, {}))
    catalog.remove("alpha", ADMIN)
    catalog.remove("alpha", ADMIN)
    classes.set_enabled(False, ADMIN)
    classes.set_enabled(False, ADMIN)
    return {"done": True}


def snapshot():
    from data_classes.models import DataClass, Settings
    from model_registry.models import ModelApproval
    from audit.models import AuditRecord

    return {
        "classes_enabled": Settings.objects.filter(pk=1, classes_enabled=True).exists(),
        "classes": sorted(DataClass.objects.values_list("name", flat=True)),
        "approvals": sorted(
            [row.pk, row.key_choice, row.approved_classes, row.gateway_fingerprint]
            for row in ModelApproval.objects.all()
        ),
        "records": AuditRecord.objects.count(),
    }


def refused_changes():
    """Changes that fail validation; each must leave state and Audit untouched."""
    from common.errors import StorageUnavailable

    _, classes, catalog = domain()
    classes.set_enabled(True, ADMIN)
    catalog.approve("alpha", ["Public"], FIRST, ADMIN)
    before = snapshot()
    attempts = [
        lambda: classes.add({"name": "public", "approved_model_ids": []}, None, ADMIN),
        lambda: classes.add({"name": "x", "approved_model_ids": []}, None, ADMIN),
        lambda: classes.add(
            {"name": "Finance", "approved_model_ids": ["missing"]}, None, ADMIN
        ),
        lambda: classes.edit(
            class_id(classes, "Public"),
            {"name": "Internal", "approved_model_ids": []},
            None,
            ADMIN,
        ),
        lambda: classes.edit(
            "missing", {"name": "Finance", "approved_model_ids": []}, None, ADMIN
        ),
        lambda: classes.remove("missing", ADMIN),
        lambda: classes.set_enabled("yes", ADMIN),
        lambda: catalog.approve("alpha", ["Missing"], FIRST, ADMIN),
        lambda: catalog.approve("alpha", ["Public"], FIRST, ADMIN, key_choice="other"),
        lambda: catalog.approve("alpha", ["Public"], "", ADMIN),
    ]
    refused = []
    for attempt in attempts:
        try:
            attempt()
        except StorageUnavailable:
            refused.append("StorageUnavailable")
        except Exception as error:  # noqa: BLE001 - the test checks the error kind.
            refused.append(type(error).__name__)
        else:
            refused.append("accepted")
    removed = catalog.remove("missing", ADMIN)
    return {
        "refused": refused,
        "removed_missing": removed,
        "before": before,
        "after": snapshot(),
    }


def failed_record_writes():
    """When writing the record fails, each change must roll back with it."""
    from unittest.mock import patch

    from audit.models import AuditRecord
    from common.errors import StorageUnavailable
    from django.db import OperationalError

    _, classes, catalog = domain()
    classes.set_enabled(True, ADMIN)
    catalog.approve("alpha", ["Public"], FIRST, ADMIN, key_choice="shared")
    classes.add({"name": "Finance", "approved_model_ids": ["alpha"]}, None, ADMIN)
    before = snapshot()
    finance = class_id(classes, "Finance")
    attempts = {
        "class mode off": lambda: classes.set_enabled(False, ADMIN),
        "add class": lambda: classes.add(
            {"name": "Legal", "approved_model_ids": ["alpha"]}, None, ADMIN
        ),
        "rename class": lambda: classes.edit(
            finance,
            {"name": "Finance team", "approved_model_ids": ["alpha"]},
            None,
            ADMIN,
        ),
        "class approvals": lambda: classes.edit(
            finance, {"name": "Finance", "approved_model_ids": []}, None, ADMIN
        ),
        "remove class": lambda: classes.remove(finance, ADMIN),
        "set up model": lambda: catalog.approve("beta", ["Public"], FIRST, ADMIN),
        "change model": lambda: catalog.approve(
            "alpha", ["Public", "Internal"], FIRST, ADMIN, key_choice="personal"
        ),
        "replace shared key": lambda: catalog.approve(
            "alpha",
            ["Public"],
            SECOND,
            ADMIN,
            key_choice="shared",
            shared_key_replaced=True,
        ),
        "remove model": lambda: catalog.remove("alpha", ADMIN),
    }
    outcome = {}
    with patch.object(
        AuditRecord.objects,
        "create",
        side_effect=OperationalError("audit write failed"),
    ):
        for name, attempt in attempts.items():
            try:
                attempt()
            except StorageUnavailable:
                outcome[name] = "StorageUnavailable"
            else:
                outcome[name] = "saved"
    return {"outcome": outcome, "before": before, "after": snapshot()}


class RemovalGateway:
    """An in-memory gateway registry that keeps revisions like agentgateway."""

    def __init__(self):
        self.models, self.refuse_delete, self.deletes = {}, False, []
        self.revision = 0

    def add(self, model_id):
        value = {"id": model_id, "name": model_id, "params": {"model": "upstream"}}
        return self.restore_model(value)

    def resources(self):
        return 200, {"resources": json.loads(json.dumps(list(self.models.values())))}

    def delete_model(self, model_id):
        self.deletes.append(model_id)
        if self.refuse_delete:
            return 503, {"error": "Gateway unavailable"}
        del self.models[model_id]
        return 200, {}

    def restore_model(self, value):
        # Every write gets a new revision, so a restored model is a new revision.
        self.revision += 1
        self.models[value["id"]] = {
            "id": value["id"],
            "revision": self.revision,
            "value": json.loads(json.dumps(value)),
        }
        return 200, {}


def removal_rollbacks():
    """Model removal keeps Keeplane and the gateway consistent when a step fails."""
    from unittest.mock import patch

    from audit.models import AuditRecord
    from common.errors import StorageUnavailable
    from django.db import OperationalError
    from model_registry.fingerprints import fingerprint
    from model_registry.models import ModelApproval
    from model_registry.removal import remove_model_setup

    audit, _, catalog = domain()
    audit.set_option("settings", True)
    gateway = RemovalGateway()

    def set_up(model_id, owned=True):
        gateway.add(model_id)
        _, registry = gateway.resources()
        catalog.approve(
            model_id,
            [],
            fingerprint(model_id, registry["resources"]),
            None,
            owned_by_keeplane=owned,
        )

    def state(model_id):
        _, registry = gateway.resources()
        row = ModelApproval.objects.filter(pk=model_id).first()
        return {
            "in_gateway": model_id in gateway.models,
            "approved": row is not None,
            "pinned_to_gateway": row is not None
            and row.gateway_fingerprint
            == fingerprint(model_id, registry["resources"]),
            "records": AuditRecord.objects.count(),
        }

    def remove(model_id):
        try:
            status, body = remove_model_setup(
                model_id, ADMIN, catalog, gateway, None, ""
            )
        except StorageUnavailable:
            status, body = 503, {"error": "StorageUnavailable"}
        return {"status": status, "error": body.get("error"), **state(model_id)}

    from django.db import connections

    wrapper = connections["default"]
    real_commit = wrapper.commit
    commits = []

    def commit_fails_once():
        # The first commit is the removal's; the rollback's re-pin may commit.
        if not commits:
            commits.append("failed")
            raise OperationalError("commit failed")
        return real_commit()

    result = {}
    set_up("record-fails")
    with patch.object(
        AuditRecord.objects, "create", side_effect=OperationalError("audit down")
    ):
        result["record write fails"] = remove("record-fails")
    set_up("gateway-refuses")
    gateway.refuse_delete = True
    result["gateway refuses"] = remove("gateway-refuses")
    gateway.refuse_delete = False
    set_up("commit-fails")
    with patch.object(wrapper, "commit", commit_fails_once):
        result["commit fails"] = remove("commit-fails")
    landed = []

    def commit_lands_then_fails():
        # The connection drops after the server kept the commit.
        if not landed:
            landed.append("landed")
            real_commit()
            raise OperationalError("connection lost during commit")
        return real_commit()

    set_up("commit-lands")
    with patch.object(wrapper, "commit", commit_lands_then_fails):
        result["commit lands but reports failure"] = remove("commit-lands")
    set_up("outside", owned=False)
    with patch.object(
        AuditRecord.objects, "create", side_effect=OperationalError("audit down")
    ):
        result["outside, record write fails"] = remove("outside")
    result["outside"] = remove("outside")
    set_up("normal")
    result["normal"] = remove("normal")
    result["gateway deletes"] = gateway.deletes
    result["records"] = [
        row.description for row in AuditRecord.objects.order_by("pk")
    ]
    return result


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
    if action == "settings_changes":
        return settings_changes()
    if action == "refused_changes":
        return refused_changes()
    if action == "failed_record_writes":
        return failed_record_writes()
    if action == "removal_rollbacks":
        return removal_rollbacks()
    audit, identity, password_file = services()
    if action == "audit_option":
        return audit.set_option(command["kind"], command["enabled"])
    if action == "options":
        return audit.options()
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
