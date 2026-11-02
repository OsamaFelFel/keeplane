"""The Audit storage guide matches how records are stored, kept and exported.

Cases ASG-01 to ASG-08 in audit-storage-guide-cases.md. Names in the guide are
read as text and compared with the models, migrations, URLs, settings, the
Docker preview and the chart. The export and size cases run the guide's own
commands against a temporary SQLite database in separate processes.
"""

import inspect
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from audit.contracts import RECORD_KINDS
from audit.models import AuditOption, AuditRecord
from django.apps import apps
from django.core.management import get_commands, load_command_class
from django.db import migrations
from django.db.migrations.loader import MigrationLoader
from django.urls import URLPattern, URLResolver, get_resolver

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "components/control-plane"
GUIDE_PATH = ROOT / "docs/guide/audit-storage.md"
GUIDE = GUIDE_PATH.read_text()
LOCAL_GUIDE = (ROOT / "docs/guide/audit-local.md").read_text()
COMPOSE = (ROOT / "compose.yaml").read_text()
SETTINGS = (APP / "config/settings.py").read_text()
TEMPLATES = ROOT / "deploy/helm/keeplane/templates"
AUDIT_TABLES = {"auditrecord", "auditoption"}
AUDIT_TABLE_NAME = re.compile(r"audit_?(record|option)", re.IGNORECASE)
RECORD_COLUMNS = ["id", "kind", "happened_at", "actor_id", "actor_name", "description"]


def shell_commands():
    """Every command line in the guide's sh blocks, continuations joined."""
    commands = []
    for block in re.findall(r"^```sh\n(.*?)^```", GUIDE, re.DOTALL | re.MULTILINE):
        for line in re.sub(r"\s*\\\n\s*", " ", block).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                commands.append(line)
    return commands


COMMANDS = shell_commands()


def test_asg01_tables_columns_and_kinds_are_the_models():
    assert AuditRecord._meta.db_table == "accounts_auditrecord"
    assert AuditOption._meta.db_table == "accounts_auditoption"
    for table in ("accounts_auditrecord", "accounts_auditoption"):
        assert f"`{table}`" in GUIDE
    columns = [field.column for field in AuditRecord._meta.concrete_fields]
    assert columns == RECORD_COLUMNS
    for column in columns:
        assert f"`{column}`" in GUIDE, column
    assert "only those six columns" in GUIDE and len(columns) == 6
    listed = GUIDE.split("`kind` is one of ", 1)[1].split(".", 1)[0]
    assert re.findall(r"`(\w+)`", listed) == list(RECORD_KINDS)
    # A held-back request's reference is random, as the guide says.
    producer = (APP / "model_registry/held_request_records.py").read_text()
    assert 'return "HR-" + secrets.token_hex(6)' in producer
    assert "`HR-` and 12 hex digits" in GUIDE


def test_asg02_database_locations_are_the_apps():
    assert '"KEEPLANE_SQLITE_PATH", "/state/keeplane.sqlite3"' in SETTINGS
    assert 'if os.environ.get("KEEPLANE_DATABASE_HOST"):' in SETTINGS
    assert set(re.findall(r"KEEPLANE_SQLITE_PATH: (\S+)", COMPOSE)) == {
        "/state/database/keeplane.sqlite3"
    }
    assert "- account-data:/state" in COMPOSE
    assert "`/state/database/keeplane.sqlite3` in the `account-data` volume" in GUIDE
    assert "`/state/keeplane.sqlite3` on the app's state volume" in GUIDE
    assert "(`KEEPLANE_DATABASE_HOST` set)" in GUIDE
    values = (ROOT / "deploy/helm/keeplane/values.yaml").read_text()
    assert re.search(
        r"^  postgres:\n(?:    .*\n)*?    database: ", values, re.MULTILINE
    )
    assert "`app.postgres.database`" in GUIDE


def test_asg03_nothing_in_the_app_deletes_or_changes_records():
    # The Audit API: records are only read; switches are read and set.
    methods = {}
    for pattern in __import__("audit.urls", fromlist=["urlpatterns"]).urlpatterns:
        allowed = set(pattern.callback.cls.http_method_names) - {"options"}
        methods[str(pattern.pattern)] = allowed
    assert methods == {
        "api/audit/options": {"get"},
        "api/audit/options/<str:kind>": {"put"},
        "api/audit/records": {"get"},
    }

    # No other route serves an Audit API.
    def routes(resolver, prefix=""):
        for entry in resolver.url_patterns:
            if isinstance(entry, URLResolver):
                yield from routes(entry, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                yield prefix + str(entry.pattern), entry.callback

    api = {route for route, view in routes(get_resolver()) if "api/audit" in route}
    assert api == set(methods)

    # Only these files touch the records table, and only to add, list or count.
    readers = {}
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if "/migrations/" in relative:
            continue
        text = path.read_text()
        if re.search("auditrecord", text, re.IGNORECASE):
            readers[relative] = set(re.findall(r"AuditRecord\.objects\.(\w+)", text))
    assert readers == {
        "audit/models.py": set(),
        "audit/services.py": {"create", "all"},
        "common/restore_check.py": {"count", "order_by"},
    }
    services = (APP / "audit/services.py").read_text()
    assert not re.search(
        r"\.(delete|update|bulk_update|raw|extra)\(|cursor\(", services
    )

    # No relation can cascade a removal (of a user, say) into the records.
    assert not [field for field in AuditRecord._meta.get_fields() if field.is_relation]
    for model in apps.get_models():
        for field in model._meta.get_fields():
            assert field.related_model not in (AuditRecord, AuditOption), (model, field)
    assert "Removing a user keeps their records." in GUIDE
    assert "there is no delete action" in GUIDE


def database_operations(operation):
    if isinstance(operation, migrations.SeparateDatabaseAndState):
        for inner in operation.database_operations:
            yield from database_operations(inner)
    else:
        yield operation


def touched_models(operation):
    names = (
        getattr(operation, attr, None)
        for attr in ("name", "model_name", "old_name", "new_name")
    )
    return {name.lower() for name in names if isinstance(name, str)}


def test_asg04_migrations_never_drop_or_rewrite_records():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    touching = []
    for (app, name), migration in sorted(loader.disk_migrations.items()):
        for operation in migration.operations:
            for change in database_operations(operation):
                if isinstance(change, migrations.RunSQL):
                    assert not AUDIT_TABLE_NAME.search(str(change.sql)), (app, name)
                elif isinstance(change, migrations.RunPython):
                    source = inspect.getsource(sys.modules[change.code.__module__])
                    assert not AUDIT_TABLE_NAME.search(source), (app, name)
                elif touched_models(change) & AUDIT_TABLES:
                    touching.append(
                        (
                            app,
                            name,
                            type(change).__name__,
                            sorted(touched_models(change) & AUDIT_TABLES),
                        )
                    )
    # The tables are created once; every later move changes ownership only.
    assert touching == [
        ("accounts", "0001_initial", "CreateModel", ["auditoption"]),
        ("accounts", "0001_initial", "CreateModel", ["auditrecord"]),
        ("accounts", "0001_initial", "AddIndex", ["auditrecord"]),
    ]
    # The migration steps the guide names run `migrate` before serving.
    assert re.search(
        r"^  app-migrate:\n(?:    .*\n)*?    command: \[.*manage\.py migrate",
        COMPOSE,
        re.MULTILINE,
    )
    app = (TEMPLATES / "app.yaml").read_text()
    assert re.search(
        r"- name: migrate-local-database\n(?:.*\n){1,12}?.*manage\.py migrate", app
    )
    job = (TEMPLATES / "postgres-migrate.yaml").read_text()
    assert "name: {{ .Release.Name }}-accounts-migrate" in job
    assert '"helm.sh/hook": pre-install,pre-upgrade' in job
    for step in (
        "`app-migrate` service",
        "`migrate-local-database`",
        "`<release>-accounts-migrate`",
    ):
        assert step in GUIDE, step


def test_asg05_commands_are_the_apps_and_run_where_the_backup_guide_runs_them():
    named = set(re.findall(r"manage\.py (\w+)((?: (?:--?[\w-]+|[\w.]+))*)", GUIDE))
    assert {name for name, _ in named} == {"verify_restore", "dumpdata"}
    commands = get_commands()
    for name, arguments in named:
        parser = load_command_class(commands[name], name).create_parser(
            "manage.py", name
        )
        parser.parse_args(arguments.split())
    docker = [line for line in COMMANDS if line.startswith("docker ")]
    kubectl = [line for line in COMMANDS if line.startswith("kubectl ")]
    assert len(docker) == len(kubectl) == 2
    for line in docker:
        assert line.startswith("docker compose exec -T app python manage.py "), line
    for line in kubectl:
        assert line.startswith(
            'kubectl -n "$NS" exec deploy/"$RELEASE"-app -c app -- python /app/manage.py '
        ), line

    # Each Docker command has the same Kubernetes form.
    def tail(line):
        return line.split("manage.py ", 1)[1]

    assert sorted(map(tail, docker)) == sorted(map(tail, kubectl))
    assert "`audit_records`" in GUIDE
    check = (APP / "common/restore_check.py").read_text()
    assert '"audit_records": {' in check and '"newest":' in check


def run_app(database, *arguments, script=None):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("KEEPLANE_", "DJANGO_"))
    }
    signing = database.parent / "signing"
    if not signing.exists():
        signing.write_text(secrets.token_urlsafe(48))
    env.update(
        KEEPLANE_SQLITE_PATH=str(database),
        DJANGO_SETTINGS_MODULE="config.settings",
        DJANGO_SECRET_KEY_FILE=str(signing),
        PROVIDER_KEY_DIR=str(database.parent),
        PYTHONPATH=os.pathsep.join([str(APP), str(ROOT)]),
        PYTHONDONTWRITEBYTECODE="1",
    )
    command = [sys.executable, "manage.py", *arguments]
    if script is not None:
        command = [
            sys.executable,
            "manage.py",
            "shell",
            "--verbosity",
            "0",
            "-c",
            script,
        ]
    return subprocess.run(
        command,
        cwd=APP,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


WRITE_RECORDS = """
from audit.services import DjangoAuditStore
from model_registry.model_answer_records import description
audit = DjangoAuditStore()
audit.record_break_glass({"id": "1", "username": "first-admin"})
audit.record("model_answers", "7", "dev-one", "never written: the kind is off")
audit.set_option("model_answers", True)
for n in range(3):
    audit.record("model_answers", "7", "dev-one", description("alpha", f"payments-{n}"))
"""


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "keeplane.sqlite3"
    migrated = run_app(path, "migrate", "--noinput")
    assert migrated.returncode == 0, migrated.stderr
    return path


def rows(path):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT "
            + ", ".join(RECORD_COLUMNS)
            + " FROM accounts_auditrecord ORDER BY id"
        ).fetchall()


def test_asg06_export_reads_every_record_and_leaves_them(database):
    written = run_app(database, script=WRITE_RECORDS)
    assert written.returncode == 0, written.stderr
    before = rows(database)
    assert [row[1] for row in before] == ["break_glass_sign_ins"] + [
        "model_answers"
    ] * 3

    (export,) = [
        line for line in COMMANDS if line.startswith("docker ") and "dumpdata" in line
    ]
    arguments = export.split("python manage.py ", 1)[1].split(" > ", 1)[0].split()
    exported = run_app(database, *arguments)
    assert exported.returncode == 0, exported.stderr
    entries = json.loads(exported.stdout)
    assert [entry["model"] for entry in entries] == ["audit.auditrecord"] * 4
    assert [entry["pk"] for entry in entries] == [row[0] for row in before]
    for entry, row in zip(entries, before):
        fields = entry["fields"]
        assert sorted(fields) == sorted(RECORD_COLUMNS[1:])
        assert [
            fields[name] for name in RECORD_COLUMNS[1:] if name != "happened_at"
        ] == [row[1], row[3], row[4], row[5]]
        assert fields["happened_at"].endswith("Z"), fields["happened_at"]
    assert rows(database) == before

    # The PostgreSQL export selects the same columns from the same table.
    (copy,) = re.findall(r"\\copy \((SELECT [^)]+)\)", GUIDE)
    assert copy == (
        "SELECT " + ", ".join(RECORD_COLUMNS) + " FROM accounts_auditrecord ORDER BY id"
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(copy).fetchall() == before
    assert "pg_total_relation_size('accounts_auditrecord')" in GUIDE

    # verify_restore reports the count and newest time the guide points to.
    report = json.loads(run_app(database, "verify_restore").stdout)
    counted = report["records"]["audit_records"]
    assert counted["total"] == 4
    assert counted["newest"] == entries[-1]["fields"]["happened_at"][:19] + "+00:00"


MEASURE = """
import os
from django.db import connection, transaction
from audit.services import DjangoAuditStore
from model_registry.model_answer_records import description
path = connection.settings_dict["NAME"]
audit = DjangoAuditStore()
audit.set_option("model_answers", True)
def size():
    connection.cursor().execute("VACUUM")
    return os.path.getsize(path)
empty = size()
with transaction.atomic():
    for n in range({count}):
        audit.record("model_answers", str(n % 500), f"developer-{{n % 500:03d}}",
                     description("claude-sonnet-4-5-20250929", f"payments-api-{{n % 50}}"))
print((size() - empty) / {count})
"""


def test_asg07_a_typical_record_takes_less_space_than_the_guide_says(database):
    (bound,) = re.findall(r"takes under (\d+) bytes", GUIDE)
    (million,) = re.findall(r"a million records take under (\d+) megabytes", GUIDE)
    # Under N bytes each is under N megabytes per million.
    assert int(million) == int(bound)
    measured = run_app(database, script=MEASURE.format(count=5000))
    assert measured.returncode == 0, measured.stderr
    per_record = float(measured.stdout.strip())
    assert 0 < per_record < int(bound), per_record


def slug(heading):
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def anchors(path):
    return {
        slug(line.lstrip("#"))
        for line in path.read_text().splitlines()
        if line.startswith("#")
    }


def test_asg08_links_resolve_and_the_audit_guide_links_here():
    links = re.findall(r"\]\(([^)\s]+)\)", GUIDE)
    assert links
    for link in links:
        if link.startswith("http"):
            continue
        target, _, anchor = link.partition("#")
        path = (GUIDE_PATH.parent / target).resolve() if target else GUIDE_PATH
        assert path.exists(), link
        if anchor:
            assert anchor in anchors(path), link
    assert "(audit-storage.md)" in LOCAL_GUIDE
    assert (
        "(audit-storage.md#export-records)"
        in (ROOT / "docs/guide/backup-and-restore.md").read_text()
    )
