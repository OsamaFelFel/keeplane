"""Back up a populated Keeplane database, restore it fresh and check what survives.

Task 002-02 (durable databases, backup and restore) and 003-03 (backup and
restore of production identity). The plain-English cases are in
backup-restore-cases.md and the procedure in docs/guide/backup-and-restore.md.
Every step runs the real control plane in its own process with production
settings, the way an installer's app copy, migration Job and shell do.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "components/control-plane"
PROBE = ROOT / "tests/fixtures/backup_restore_probe.py"
POSTGRES_ENV = "KEEPLANE_TEST_POSTGRES_HOST"
REVISIONS = {"keeplane-model": 3, "customer-model": 7, "personal-model": 2}
# The guide's SQLite commands, as written there. SQLITE_COPY copies one
# database into another with SQLite's online backup, for a backup (live file
# to copy) and for a restore (backup into the live file); its source must exist.
SQLITE_COPY = (
    "import sqlite3,sys; s=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); "
    "d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()"
)
# The guide's SQL for a PostgreSQL restore target, line for line, with the
# example names replaced by this run's roles and database.
RESTORE_TARGET_SQL = (
    'CREATE DATABASE "{database}" OWNER "{migrate}"',
    'REVOKE ALL ON DATABASE "{database}" FROM PUBLIC',
    'GRANT CONNECT ON DATABASE "{database}" TO "{app}"',
)
OLDER_SERVER_SQL = 'ALTER SCHEMA public OWNER TO "{migrate}"'
# Streams a backup into the app's volume as the app's own user.
COPY_IN = "import shutil,sys; shutil.copyfileobj(sys.stdin.buffer, open(sys.argv[1], 'xb'))"


def private_file(path, value):
    path.write_text(value)
    path.chmod(0o600)
    return path


class SQLiteDatabases:
    engine = "sqlite"

    def __init__(self, root):
        self.root = root

    def path(self, name):
        return self.root / (name + ".sqlite3")

    def env(self, name, migrate=False):
        return {"KEEPLANE_SQLITE_PATH": str(self.path(name))}

    def create(self, name):
        assert not self.path(name).exists()

    def backup(self, name, destination):
        # The app may keep serving: the backup API copies a consistent snapshot.
        subprocess.run(
            [sys.executable, "-c", SQLITE_COPY, str(self.path(name)), str(destination)],
            check=True, timeout=60,
        )

    def restore(self, source, name, prepare):
        # A fresh installation has already migrated its own empty database;
        # the online backup replaces all of it, migration ledger included.
        prepare()
        incoming = self.root / (name + "-incoming.sqlite3")
        with open(source, "rb") as stream:
            subprocess.run([sys.executable, "-c", COPY_IN, str(incoming)],
                           stdin=stream, check=True, timeout=60)
        subprocess.run(
            [sys.executable, "-c", SQLITE_COPY, str(incoming), str(self.path(name))],
            check=True, timeout=60,
        )
        incoming.unlink()

    def close(self):
        pass


class PostgresDatabases:
    """Disposable roles and databases on a supplied server, as the chart guide sets up."""

    engine = "postgresql"

    def __init__(self, root, psycopg, tools):
        self.root, self.psycopg, self.tools = root, psycopg, tools
        self.prefix = "kl_backup_" + uuid.uuid4().hex[:8]
        self.migrate_role, self.app_role = self.prefix + "_migrate", self.prefix + "_app"
        self.passwords = {
            role: private_file(root / role, secrets.token_urlsafe(24))
            for role in (self.migrate_role, self.app_role)
        }
        self.admin = {
            "host": os.environ[POSTGRES_ENV],
            "port": os.environ.get("KEEPLANE_TEST_POSTGRES_PORT", "5432"),
            "user": os.environ["KEEPLANE_TEST_POSTGRES_USER"],
            "password": Path(os.environ["KEEPLANE_TEST_POSTGRES_PASSWORD_FILE"])
            .read_text().strip(),
            "dbname": os.environ.get("KEEPLANE_TEST_POSTGRES_NAME", "postgres"),
            "sslmode": os.environ.get("KEEPLANE_TEST_POSTGRES_SSLMODE", "disable"),
        }
        self.databases = []
        with self.connect() as admin:
            for role in (self.migrate_role, self.app_role):
                admin.execute(
                    f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                    f"NOINHERIT PASSWORD '{self.passwords[role].read_text()}'"
                )

    def connect(self, dbname=None):
        values = dict(self.admin, dbname=dbname or self.admin["dbname"])
        return self.psycopg.connect(**values, autocommit=True)

    def database(self, name):
        return self.prefix + "_" + name

    def env(self, name, migrate=False):
        role = self.migrate_role if migrate else self.app_role
        return {
            "KEEPLANE_DATABASE_HOST": self.admin["host"],
            "KEEPLANE_DATABASE_PORT": self.admin["port"],
            "KEEPLANE_DATABASE_NAME": self.database(name),
            "KEEPLANE_DATABASE_USER": role,
            "KEEPLANE_DATABASE_PASSWORD_FILE": str(self.passwords[role]),
            "KEEPLANE_DATABASE_SSLMODE": self.admin["sslmode"],
        }

    def create(self, name, schema_privileges=True):
        """A fresh database with the privileges the PostgreSQL guide asks for.

        Without schema_privileges it runs only the restore guide's SQL: the
        schema grants and default privileges must then come from the dump.
        """
        database = self.database(name)
        with self.connect() as admin:
            for statement in RESTORE_TARGET_SQL:
                admin.execute(statement.format(
                    database=database, migrate=self.migrate_role, app=self.app_role))
            older_server = admin.info.server_version < 150000
        self.databases.append(database)
        if older_server:
            # The guide's extra line for PostgreSQL 14 and older.
            with self.connect(database) as admin_database:
                admin_database.execute(OLDER_SERVER_SQL.format(migrate=self.migrate_role))
        if not schema_privileges:
            return
        with self.connect(database) as owner_database:
            owner_database.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            owner_database.execute(f'GRANT USAGE ON SCHEMA public TO "{self.app_role}"')
            for grant in (
                "SELECT, INSERT, UPDATE, DELETE ON TABLES",
                "USAGE, SELECT ON SEQUENCES",
            ):
                owner_database.execute(
                    f'ALTER DEFAULT PRIVILEGES FOR ROLE "{self.migrate_role}" '
                    f'IN SCHEMA public GRANT {grant} TO "{self.app_role}"'
                )

    def tool(self, name, *arguments):
        environment = dict(
            os.environ,
            PGHOST=self.admin["host"], PGPORT=self.admin["port"],
            PGUSER=self.migrate_role, PGSSLMODE=self.admin["sslmode"],
            PGPASSWORD=self.passwords[self.migrate_role].read_text(),
        )
        subprocess.run(
            [str(self.tools / name), *arguments],
            env=environment, check=True, capture_output=True, timeout=120,
        )

    def backup(self, name, destination):
        # The guide's command: a consistent custom-format dump by the owning role.
        self.tool("pg_dump", "--format=custom", "--dbname", self.database(name),
                  "--file", str(destination))

    def restore(self, source, name, prepare):
        # pg_restore needs a new, empty database: never migrate it first. Only
        # the guide's SQL runs; grants to the app role must come from the dump.
        self.create(name, schema_privileges=False)
        self.tool("pg_restore", "--exit-on-error", "--single-transaction",
                  "--no-owner", "--dbname", self.database(name), str(source))

    def close(self):
        with self.connect() as admin:
            for database in self.databases:
                admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            for role in (self.app_role, self.migrate_role):
                admin.execute(f'DROP ROLE IF EXISTS "{role}"')


def postgres_tools():
    configured = os.environ.get("KEEPLANE_TEST_POSTGRES_BIN")
    if configured:
        return Path(configured)
    found = shutil.which("pg_restore")
    if found:
        return Path(found).parent
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin/pg_restore"))
    return candidates[-1].parent if candidates else None


class Installation:
    """Run Keeplane commands against one database, signing secret and key folder."""

    def __init__(self, databases, root):
        self.databases, self.root = databases, root
        self.signing = private_file(root / "signing-secret", secrets.token_urlsafe(48))
        self.other_signing = private_file(root / "other-signing-secret", secrets.token_urlsafe(48))
        self.first_admin = private_file(root / "first-admin-password", secrets.token_urlsafe(24))

    def env(self, database, keys, signing=None, migrate=False):
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("KEEPLANE_", "DJANGO_", "PG"))
        }
        env.update(
            self.databases.env(database, migrate=migrate),
            PYTHONPATH=os.pathsep.join([str(APP), str(ROOT)]),
            PYTHONDONTWRITEBYTECODE="1",
            DJANGO_SETTINGS_MODULE="config.settings",
            DJANGO_SECRET_KEY_FILE=str(signing or self.signing),
            FIRST_ADMIN_PASSWORD_FILE=str(self.first_admin),
            PROVIDER_KEY_DIR=str(keys),
        )
        return env

    def manage(self, database, keys, *arguments, signing=None, migrate=False, check=True):
        result = subprocess.run(
            [sys.executable, str(APP / "manage.py"), *arguments],
            env=self.env(database, keys, signing, migrate),
            capture_output=True, text=True, timeout=180, check=False,
        )
        if check and result.returncode:
            pytest.fail(" ".join(arguments) + " failed: " + result.stderr[-3000:])
        return result

    def migrate(self, database, keys, *target):
        self.manage(database, keys, "migrate", "--noinput", *target, migrate=True)

    def verify(self, database, keys, signing=None):
        result = self.manage(database, keys, "verify_restore", signing=signing, check=False)
        assert result.returncode in (0, 1), result.stderr[-3000:]
        report = json.loads(result.stdout)
        assert report["passed"] is (result.returncode == 0)
        return report, result.stdout

    def probe(self, action, database, keys, signing=None, revisions=REVISIONS, **values):
        result = subprocess.run(
            [sys.executable, str(PROBE), action],
            input=json.dumps({"revisions": revisions, **values}),
            env=self.env(database, keys, signing),
            capture_output=True, text=True, timeout=180, check=False,
        )
        if result.returncode:
            pytest.fail(action + " failed: " + result.stderr[-3000:])
        return json.loads(result.stdout)


def copy_keys(source, destination):
    """The guide's file backup: tar keeps names, owners and modes."""
    archive = destination.parent / (destination.name + ".tar")
    subprocess.run(["tar", "--numeric-owner", "-C", str(source), "-cpf", str(archive), "."],
                   check=True, timeout=60)
    destination.mkdir(mode=0o700)
    subprocess.run(["tar", "--numeric-owner", "-C", str(destination), "-xpf", str(archive)],
                   check=True, timeout=60)
    return destination


@pytest.fixture(scope="module", params=["sqlite", "postgresql"])
def scenario(request, tmp_path_factory):
    root = tmp_path_factory.mktemp("backup-" + request.param)
    root.chmod(0o700)
    if request.param == "sqlite":
        databases = SQLiteDatabases(root)
    else:
        if not os.environ.get(POSTGRES_ENV):
            pytest.skip("Set KEEPLANE_TEST_POSTGRES_* to a disposable PostgreSQL server")
        psycopg = pytest.importorskip("psycopg")
        tools = postgres_tools()
        if tools is None or not (tools / "pg_dump").exists():
            pytest.skip("Install pg_dump and pg_restore or set KEEPLANE_TEST_POSTGRES_BIN")
        databases = PostgresDatabases(root, psycopg, tools)
    try:
        yield run_scenario(Installation(databases, root), databases, root)
    finally:
        databases.close()


def run_scenario(app, databases, root):
    seen = {"engine": databases.engine}
    keys = root / "provider-keys"
    keys.mkdir(mode=0o700)
    databases.create("original")
    app.migrate("original", keys)
    seen["populated"] = app.probe("populate", "original", keys)
    seen["before"] = app.probe("inspect", "original", keys, tokens=seen["populated"]["tokens"])
    # Save the report when taking the backup, to compare after restoring it.
    seen["before_report"], _ = app.verify("original", keys)

    # Back up the database and the provider-key files together.
    backup = root / "keeplane-app.backup"
    databases.backup("original", backup)
    key_backup = copy_keys(keys, root / "provider-keys-backup")

    # Changes made after the backup that a restore of it undoes.
    app.probe("withdraw", "original", keys, **seen["populated"])
    seen["after_withdraw"] = app.probe("inspect", "original", keys,
                                       tokens=seen["populated"]["tokens"])

    def restore(source, name):
        databases.restore(source, name, lambda: app.migrate(name, keys))

    # Restore into a fresh database and a fresh key folder, then migrate and verify.
    restore(backup, "restored")
    restored_keys = copy_keys(key_backup, root / "provider-keys-restored")
    app.migrate("restored", restored_keys)
    seen["restored_report"], seen["restored_output"] = app.verify("restored", restored_keys)
    seen["other_secret_report"], seen["other_secret_output"] = app.verify(
        "restored", restored_keys, signing=app.other_signing)
    seen["other_secret"] = app.probe("inspect", "restored", restored_keys,
                                     signing=app.other_signing,
                                     tokens=seen["populated"]["tokens"])
    seen["restored"] = app.probe("inspect", "restored", restored_keys,
                                 tokens=seen["populated"]["tokens"])

    # The database without its key files, and key files restored with wrong modes.
    empty = root / "provider-keys-empty"
    empty.mkdir(mode=0o700)
    seen["no_keys_report"], _ = app.verify("restored", empty)
    seen["no_keys"] = app.probe("inspect", "restored", empty, tokens={})
    loose = copy_keys(key_backup, root / "provider-keys-loose")
    for path in loose.iterdir():
        path.chmod(0o644)
    seen["loose_keys_report"], _ = app.verify("restored", loose)
    seen["loose_keys"] = app.probe("inspect", "restored", loose, tokens={})

    # The gateway restored to a different point than the app database.
    seen["gateway_changed"] = app.probe(
        "inspect", "restored", restored_keys, tokens={},
        revisions=dict(REVISIONS, **{"keeplane-model": 4, "customer-model": None}))

    # A backup taken by an older Keeplane version, before its last migration.
    older_keys = root / "provider-keys-older"
    older_keys.mkdir(mode=0o700)
    databases.create("older")
    app.migrate("older", older_keys)
    older = app.probe("populate", "older", older_keys)
    app.migrate("older", older_keys, "model_registry", "0007")
    databases.backup("older", root / "older.backup")
    restore(root / "older.backup", "older_restored")
    older_restored_keys = copy_keys(older_keys, root / "provider-keys-older-restored")
    seen["older_report"], _ = app.verify("older_restored", older_restored_keys)
    app.migrate("older_restored", older_restored_keys)
    seen["older_migrated_report"], _ = app.verify("older_restored", older_restored_keys)
    seen["older_migrated"] = app.probe("inspect", "older_restored", older_restored_keys,
                                       tokens=older["tokens"])

    # A backup from a newer Keeplane version, restored into this one.
    restore(backup, "newer")
    app.probe("future_migration", "newer", restored_keys)
    seen["newer_report"], _ = app.verify("newer", restored_keys)

    # An app copy pointed at an empty database instead of the restored one.
    databases.create("empty")
    seen["empty_report"], _ = app.verify("empty", restored_keys)
    seen["secrets"] = [
        *seen["populated"]["tokens"].values(),
        app.signing.read_text(), app.other_signing.read_text(), app.first_admin.read_text(),
        "synthetic-restore-provider-key", "restore-developer-password",
        *(path.name for path in keys.iterdir()),
    ]
    return seen


def test_br01_restored_database_passes_and_matches_the_backup(scenario):
    before, restored = scenario["before_report"], scenario["restored_report"]
    assert before["passed"] and restored["passed"], restored["problems"]
    assert restored["migrations"]["pending"] == restored["migrations"]["unknown"] == []
    assert restored["database"]["engine"] == scenario["engine"]
    assert restored["records"] == before["records"]
    assert restored["records"]["accounts"] == {
        "total": 3, "active": 3, "active_admins": 2, "first_admin": True}
    # Three populated sign-ins plus the developer's password check in "before".
    assert restored["records"]["sessions"] == {"unexpired": 4, "usable": 4}
    assert restored["records"]["model_approvals"] == 3
    assert restored["developer_key_files"] == {
        "registered": 1, "present": 1, "missing": 0, "unreadable": 0, "checked": True}


def test_br02_accounts_sessions_and_cli_sign_in_survive(scenario):
    before, restored = scenario["before"], scenario["restored"]
    assert restored["accounts"] == before["accounts"] == [
        ["first-admin", "admin"], ["removed-later", "admin"],
        ["restore-developer", "developer"]]
    assert restored["sessions"] == before["sessions"] == {
        "first-admin": "admin", "removed-later": "admin", "restore-developer": "developer"}
    assert restored["password_sign_in"] and restored["cli_sign_in"]


def test_br03_classes_approvals_and_audit_records_survive(scenario):
    before, restored = scenario["before"], scenario["restored"]
    for field in ("classes_enabled", "classes", "project_class", "approvals", "eligible"):
        assert restored[field] == before[field], field
    assert restored["classes"] == ["Public", "Internal", "Confidential"]
    assert restored["project_class"] == {"id": "internal", "name": "Internal"}
    assert restored["eligible"] == ["customer-model", "keeplane-model", "personal-model"]
    assert restored["audit"] == before["audit"] and len(restored["audit"]) >= 6
    assert ["model_answers", "restore-developer",
            "Sent a task to keeplane-model for Restore project"] in restored["audit"]
    # Each inspection signs the first admin in again; none of the records is lost.
    assert restored["break_glass_records"] >= before["break_glass_records"] >= 1


def test_br04_developer_key_survives_with_its_files(scenario):
    assert scenario["before"]["developer_key"] == "matches"
    assert scenario["restored"]["developer_key"] == "matches"


def test_br05_older_backup_brings_back_what_was_withdrawn(scenario):
    withdrawn, restored = scenario["after_withdraw"], scenario["restored"]
    assert withdrawn["approvals"]["customer-model"] is None
    assert withdrawn["approvals"]["keeplane-model"] == ["Confidential"]
    assert withdrawn["eligible"] == ["personal-model"]
    assert withdrawn["sessions"]["restore-developer"] is None
    assert ["removed-later", "admin"] not in withdrawn["accounts"]
    # Restoring the earlier backup undoes all four withdrawals.
    assert restored["approvals"]["customer-model"] == ["Internal"]
    assert restored["approvals"]["keeplane-model"] == ["Internal", "Confidential"]
    assert "customer-model" in restored["eligible"] and "keeplane-model" in restored["eligible"]
    assert restored["sessions"]["restore-developer"] == "developer"
    assert ["removed-later", "admin"] in restored["accounts"]


def test_br06_a_new_signing_secret_signs_everyone_out(scenario):
    report, other = scenario["other_secret_report"], scenario["other_secret"]
    assert report["passed"]
    assert report["records"]["sessions"] == {"unexpired": 4, "usable": 0}
    assert other["sessions"] == {
        "first-admin": None, "removed-later": None, "restore-developer": None}
    assert not other["cli_sign_in"]
    # Only sign-ins end: accounts, passwords, policy and keys stay.
    assert other["password_sign_in"] and other["developer_key"] == "matches"
    assert other["accounts"] == scenario["before"]["accounts"]
    assert other["eligible"] == scenario["before"]["eligible"]


def test_br07_missing_or_loose_key_files_are_refused_and_reported(scenario):
    for name, problem, message in (
        ("no_keys", "missing", "are missing"),
        ("loose_keys", "unreadable", "file mode 0600"),
    ):
        report = scenario[name + "_report"]
        assert not report["passed"]
        assert report["developer_key_files"][problem] == 1
        assert any(message in text for text in report["problems"])
        assert scenario[name]["developer_key"] == "unavailable"


def test_br08_restored_approval_fails_closed_when_the_gateway_differs(scenario):
    changed = scenario["gateway_changed"]
    assert changed["approvals"]["keeplane-model"] == ["Internal", "Confidential"]
    assert changed["eligible"] == ["personal-model"]


def test_br09_older_schema_needs_migrate_before_serving(scenario):
    older = scenario["older_report"]
    assert not older["passed"] and "records" not in older
    assert older["migrations"]["pending"] == ["model_registry.0008_persona_rules"]
    assert "migrate" in older["problems"][0]
    migrated = scenario["older_migrated_report"]
    assert migrated["passed"], migrated["problems"]
    assert migrated["records"]["accounts"]["total"] == 3
    assert scenario["older_migrated"]["developer_key"] == "matches"
    assert scenario["older_migrated"]["sessions"]["restore-developer"] == "developer"


def test_br10_newer_backup_is_refused(scenario):
    newer = scenario["newer_report"]
    assert not newer["passed"] and "records" not in newer
    assert newer["migrations"]["unknown"] == ["model_registry.9999_from_a_newer_version"]
    assert "newer version" in newer["problems"][0]


def test_br11_an_empty_database_is_not_mistaken_for_a_restore(scenario):
    empty = scenario["empty_report"]
    assert not empty["passed"] and "records" not in empty
    assert empty["migrations"]["applied"] == 0
    assert "model_registry.0008_persona_rules" in empty["migrations"]["pending"]


def test_br12_reports_print_no_secrets(scenario):
    for output in (scenario["restored_output"], scenario["other_secret_output"]):
        for value in scenario["secrets"]:
            assert value.strip() not in output
