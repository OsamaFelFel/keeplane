"""One control-plane process for developer usage checks on a real database.

It reads one JSON command per line on stdin and answers with one JSON line, so a
test can keep two processes open on the same SQLite or PostgreSQL database.
HTTP calls go through Django's test client and the real usage routes.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client

RESOURCES = [{"id": name, "revision": 1} for name in ("coder", "outside")]


def services():
    from accounts.services import DjangoIdentity
    from audit.services import DjangoAuditStore

    audit = DjangoAuditStore()
    return audit, DjangoIdentity(Path(os.environ["FIRST_ADMIN_PASSWORD_FILE"]), audit)


def attach():
    """Use this process's identity and a fixed gateway for the model policy."""
    from accounts import authentication
    from model_registry import runtime_views
    from model_registry.policy import DjangoModelPolicy

    _, identity = services()
    gateway = SimpleNamespace(
        models=lambda: (200, {"data": [{"id": r["id"]} for r in RESOURCES]}),
        resources=lambda: (200, {"resources": RESOURCES}),
    )
    authentication.IDENTITY = identity
    runtime_views.model_policy = lambda: DjangoModelPolicy(gateway)
    settings.ALLOWED_HOSTS = ["testserver"]


def setup(project_id):
    from accounts.models import User
    from model_registry.catalog import DjangoModelCatalog
    from model_registry.fingerprints import fingerprint
    from projects.services import DjangoProjectStore

    audit, identity = services()
    tokens = {}
    for name in ("usage-dev", "usage-other"):
        password = name + "-storage-password"
        user = identity.create_user(
            {"username": name, "role": "developer", "password": password}
        )
        tokens[name] = {"id": user["id"], "token": identity.login(name, password)}
    DjangoProjectStore().register_use(
        User.objects.get(username="usage-dev").pk, project_id, "Usage storage"
    )
    DjangoModelCatalog(audit).approve("coder", [], fingerprint("coder", RESOURCES))
    return tokens


def call(command):
    client = Client(enforce_csrf_checks=True)
    for name, value in command.get("cookies", {}).items():
        client.cookies[name] = value
    headers = {}
    if command.get("token"):
        headers["HTTP_AUTHORIZATION"] = "Bearer " + command["token"]
    if command["method"] == "post":
        response = client.post(
            "/api/runtime/usage",
            data=json.dumps(command["body"]),
            content_type="application/json",
            **headers,
        )
    else:
        response = client.get(
            "/api/runtime/usage" + command.get("query", ""), **headers
        )
    body = response.content.decode()
    return {"status": response.status_code, "body": json.loads(body) if body else None}


def rows():
    from usage.models import UsageTotal

    return [
        {**row, "user_id": str(row["user_id"]), "hour": row["hour"].isoformat()}
        for row in UsageTotal.objects.order_by("hour", "model_id").values()
    ]


def held(write):
    """Run ``write`` in one transaction, kept open until the test says go.

    The process answers ``{"held": true}`` once the write is done, then waits
    for one more line before committing, so another process can be started
    against the open transaction.
    """
    from django.db import transaction

    with transaction.atomic():
        result = write()
        print(json.dumps({"held": True}), flush=True)
        sys.stdin.readline()
    return result


def add_report(command):
    from usage import totals

    return totals.add(
        command["user_id"],
        command["model"],
        {
            "input_tokens": 10,
            "output_tokens": 1,
            "requests": 1,
            "requests_without_usage": 0,
        },
        now=datetime.fromisoformat(command["at"]),
    )


def record_origin(command):
    """Record a cloud origin for the model at ``at``, as Keeplane's add flow does."""
    from model_registry import catalog
    from model_registry.models import ModelApproval

    audit, _ = services()
    moment = datetime.fromisoformat(command["at"])
    catalog.timezone = SimpleNamespace(now=lambda: moment)
    catalog.DjangoModelCatalog(audit).approve(
        command["model"],
        [],
        "definition",
        owned_by_keeplane=True,
        key_choice="personal",
        added_from=("cloud", "openai", "test-gpt"),
    )
    return ModelApproval.objects.get(pk=command["model"]).origin_hour_priced


def handle(command):
    action = command["action"]
    if action == "migrate":
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        return {"migrated": True}
    attach()
    if action == "setup":
        return setup(command["project_id"])
    if action == "call":
        return call(command)
    if action == "repeat":
        return [call(command)["status"] for _ in range(command["count"])]
    if action == "rows":
        return rows()
    if action in ("add_report", "record_origin"):
        write = {"add_report": add_report, "record_origin": record_origin}[action]
        if command.get("hold"):
            return held(lambda: write(command))
        return write(command)
    if action == "old_total":
        from usage.models import UsageTotal

        UsageTotal.objects.create(
            user_id=command["user_id"],
            model_id="coder",
            hour=datetime.fromisoformat(command["hour"]),
            requests=1,
        )
        return {"written": True}
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
