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
            and row.gateway_fingerprint == fingerprint(model_id, registry["resources"]),
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
    result["records"] = [row.description for row in AuditRecord.objects.order_by("pk")]
    return result


def services():
    from accounts.services import DjangoIdentity
    from audit.services import DjangoAuditStore

    audit = DjangoAuditStore()
    password_file = Path(os.environ["FIRST_ADMIN_PASSWORD_FILE"])
    return audit, DjangoIdentity(password_file, audit), password_file


def level_state():
    from audit.models import AuditRecord
    from model_registry.models import ComplexityLevelChoice, ModelApproval, PersonaRule

    return {
        "choices": dict(ComplexityLevelChoice.objects.values_list("level", "model_id")),
        "rules": dict(PersonaRule.objects.values_list("persona", "model_id")),
        "models": sorted(ModelApproval.objects.values_list("model_id", flat=True)),
        "records": [
            row.description
            for row in AuditRecord.objects.filter(kind="settings").order_by("pk")
        ],
    }


def level_setup():
    """Settings changes on and two set-up models, without records for the setup."""
    audit, _, catalog = domain()
    for model_id in ("alpha", "beta"):
        catalog.approve(model_id, [], FIRST, owned_by_keeplane=True)
    audit.set_option("settings", True)
    return level_state()


def level_changes():
    """Change a level, repeat it, move it, go back, and guard a removal."""
    from model_registry.levels import ModelInUse

    _, _, catalog = domain()
    models = {"alpha", "beta"}
    catalog.change_level("complex", "alpha", models, ADMIN)
    catalog.change_level("complex", "alpha", models, ADMIN)
    catalog.change_level("complex", "beta", models, ADMIN)
    try:
        catalog.remove("beta", ADMIN)
        refused = None
    except ModelInUse as error:
        refused = error.levels
    catalog.change_level("complex", None, models, ADMIN)
    catalog.change_level("complex", None, models, ADMIN)
    return {"refused": refused, **level_state()}


def rule_changes():
    """Add a persona rule, repeat it, move it, guard a removal and remove it."""
    from model_registry.levels import ModelInUse

    _, _, catalog = domain()
    models = {"alpha", "beta"}
    catalog.set_persona_rule("architect", "alpha", models, ADMIN)
    catalog.set_persona_rule("architect", "alpha", models, ADMIN)
    catalog.set_persona_rule("architect", "beta", models, ADMIN)
    try:
        catalog.remove("beta", ADMIN)
        refused = None
    except ModelInUse as error:
        refused = error.persona_rules
    catalog.set_persona_rule("architect", None, models, ADMIN)
    catalog.set_persona_rule("architect", None, models, ADMIN)
    return {"refused": refused, **level_state()}


def model_answers():
    """Write "Model answers" records through the producer the final check uses.

    Off, on, a failed write and a vanished project; the producer never raises.
    """
    import logging
    import uuid
    from unittest.mock import patch

    from accounts.models import User
    from audit.models import AuditRecord
    from django.db import OperationalError
    from model_registry.model_answer_records import record_sent_request
    from projects.models import Project

    audit, _, _ = domain()
    developer = User.objects.create(
        username="process-developer", role="developer", password="!"
    )
    project = Project.objects.create(name="payments-api")
    decision = {
        "actor_id": str(developer.pk),
        "project_id": str(project.pk),
        "model_id": "alpha",
    }
    logged = []

    class Collect(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())

    logger = logging.getLogger("model_registry.model_answer_records")
    logger.addHandler(Collect())
    result = {"off": record_sent_request(decision, audit)}
    audit.set_option("model_answers", True)
    result["on"] = record_sent_request(decision, audit)
    with patch.object(
        AuditRecord.objects, "create", side_effect=OperationalError("audit down")
    ):
        result["failed_write"] = record_sent_request(decision, audit)
    result["missing_project"] = record_sent_request(
        dict(decision, project_id=str(uuid.uuid4())), audit
    )
    result["logged"] = len(logged)
    return result


def wait_for(path, timeout=60):
    import time

    deadline = time.monotonic() + timeout
    while not Path(path).exists():
        if time.monotonic() > deadline:
            raise TimeoutError("The test never released the settings lock")
        time.sleep(0.05)


def level_race(command):
    """Hold the settings lock in the middle of one level, rule or removal step.

    The step signals command["held"] while it holds the lock and continues once
    command["release"] exists, so the test can start the other connection's
    step in between.
    """
    from model_registry.levels import LevelError, ModelInUse
    from model_registry.persona_rules import PersonaRuleError

    audit, _, catalog = domain()
    held, release = command.get("held"), command.get("release")

    def pause():
        if held:
            Path(held).write_text("held")
            wait_for(release)

    try:
        if command["step"] == "remove":

            def gateway_step():
                pause()
                return 200, {}

            removed = catalog.remove(
                command["model"], ADMIN, remove_from_gateway=gateway_step
            )
            return {"removed": removed, **level_state()}
        if held:
            recorded = audit.record_in_transaction

            def record_then_pause(*args):
                result = recorded(*args)
                pause()
                return result

            audit.record_in_transaction = record_then_pause
        if command["step"] == "persona_rule":
            catalog.set_persona_rule(
                command["persona"], command["model"], {command["model"]}, ADMIN
            )
        else:
            catalog.change_level(
                command["level"], command["model"], {command["model"]}, ADMIN
            )
        return {"changed": True, **level_state()}
    except ModelInUse as error:
        return {
            "in_use": error.levels,
            "rules_in_use": error.persona_rules,
            **level_state(),
        }
    except (LevelError, PersonaRuleError) as error:
        return {"level_error": error.message, **level_state()}


def http(command):
    """Call Keeplane's own HTTP API in this process, as a browser would.

    Answers with the status, the JSON body and the session cookie the answer
    set, if any.
    """
    from django.test import Client

    client = Client(HTTP_HOST="127.0.0.1")
    if command.get("session"):
        client.cookies["keeplane_session"] = command["session"]
    method, path = command["method"], command["path"]
    if method == "GET":
        response = client.get(path)
    else:
        response = client.generic(
            method,
            path,
            json.dumps(command.get("body", {})),
            content_type="application/json",
            HTTP_X_KEEPLANE_ACTION="1",
        )
    cookie = response.cookies.get("keeplane_session")
    try:
        body = response.json()
    except ValueError:
        body = None
    return {
        "status": response.status_code,
        "body": body,
        "session": cookie.value if cookie is not None and cookie.value else None,
    }


OUTAGE_TABLES = {"audit": "accounts_auditrecord", "session": "django_session"}


def outage(command):
    """Make the database itself refuse new rows in one table, or repair it.

    A database trigger fails every insert, so the failure comes from the
    database, not from patched application code. PostgreSQL reports a full
    disk; SQLite reports a missing table. Both are operational errors, as a
    real outage would be (a constraint error would instead make Django pick a
    new session key and try again).
    """
    table = OUTAGE_TABLES[command["table"]]
    trigger = "keeplane_test_outage_" + command["table"]
    postgres = connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        if not command["down"]:
            cursor.execute(
                f"DROP TRIGGER IF EXISTS {trigger}" + (f" ON {table}" if postgres else "")
            )
            return {"down": False}
        if postgres:
            cursor.execute(
                "CREATE OR REPLACE FUNCTION keeplane_test_outage() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "RAISE EXCEPTION 'test storage outage' USING ERRCODE = 'disk_full'; "
                "END $$"
            )
            cursor.execute(
                f"CREATE TRIGGER {trigger} BEFORE INSERT ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION keeplane_test_outage()"
            )
        else:
            cursor.execute(
                f"CREATE TRIGGER {trigger} BEFORE INSERT ON {table} "
                "BEGIN INSERT INTO keeplane_test_storage_offline VALUES (1); END"
            )
    return {"down": True}


def stored():
    """Row counts and the full stored text of every Audit record."""
    from audit.models import AuditRecord
    from django.contrib.sessions.models import Session

    return {
        "sessions": Session.objects.count(),
        "records": AuditRecord.objects.count(),
        "record_text": [
            [row.kind, row.actor_id, row.actor_name, row.description]
            for row in AuditRecord.objects.order_by("pk")
        ],
    }


def handle(command):
    action = command["action"]
    if action == "http":
        return http(command)
    if action == "outage":
        return outage(command)
    if action == "stored":
        return stored()
    if action == "level_setup":
        return level_setup()
    if action == "level_changes":
        return level_changes()
    if action == "rule_changes":
        return rule_changes()
    if action == "level_race":
        return level_race(command)
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
    if action == "model_answers":
        return model_answers()
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
