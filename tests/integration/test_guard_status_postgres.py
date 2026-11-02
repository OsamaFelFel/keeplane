"""PostgreSQL roles for the guard-status table and the enroller (ADR 027).

Cases GS-PG-01 to GS-PG-10 in guard-status-cases.md. Each run creates its own
roles and database on a disposable server named by ``KEEPLANE_TEST_POSTGRES_*``
(CI's PostgreSQL job sets them; elsewhere these cases are skipped), migrates
as the migration role, runs ``configure_guard_status_access`` and then connects
as each role, the way the app and each copy's enroller would.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.integration.test_audit_persistence import POSTGRES_ENV

ROOT = Path(__file__).resolve().parents[2]
TABLE = "model_registry_gatewayguardstatus"
APPROVALS = "accounts_modelapproval"
COPY, OTHER = "keeplane-gateway-0", "keeplane-gateway-1"
DECLARATION = {
    "version": 2,
    "enabled": True,
    "file_digest": "a" * 64,
    "effective_digest": "b" * 64,
    "applied_digest": "c" * 64,
    "models": {
        "demo": {
            "fingerprint": "d" * 64,
            "key_choice": "none",
            "key_name": "",
            "key_digest": "",
        }
    },
}


def admin_target():
    return {
        "host": os.environ[POSTGRES_ENV],
        "port": os.environ.get("KEEPLANE_TEST_POSTGRES_PORT", "5432"),
        "user": os.environ["KEEPLANE_TEST_POSTGRES_USER"],
        "password": Path(os.environ["KEEPLANE_TEST_POSTGRES_PASSWORD_FILE"])
        .read_text()
        .strip(),
        "dbname": os.environ.get("KEEPLANE_TEST_POSTGRES_NAME", "postgres"),
        "sslmode": os.environ.get("KEEPLANE_TEST_POSTGRES_SSLMODE", "disable"),
    }


class Cluster:
    """A database owned by a migration role, with the app and enroller roles."""

    def __init__(self, psycopg, tmp_path):
        self.psycopg, self.admin = psycopg, admin_target()
        suffix = uuid.uuid4().hex[:10]
        self.database = "keeplane_guard_" + suffix
        self.roles = {
            name: f"kgs_{name}_{suffix}"
            for name in ("owner", "app", "enroller", "status0", "status1", "loose")
        }
        self.password = secrets.token_urlsafe(24)
        self.files = tmp_path
        (tmp_path / "password").write_text(self.password + "\n")
        (tmp_path / "signing").write_text(secrets.token_urlsafe(48))

    def sql(self, statement, database=None):
        with self.psycopg.connect(
            **{**self.admin, "dbname": database or self.admin["dbname"]},
            autocommit=True,
        ) as connection:
            connection.execute(statement)

    def create(self):
        quoted = self.psycopg.sql.Literal(self.password).as_string(None)
        for role in self.roles.values():
            self.sql(f"CREATE ROLE {role} LOGIN PASSWORD {quoted}")
        # The guide's operator steps: read-only by default for the enroller
        # and status roles; the app and migration roles as in postgres-accounts.
        for name in ("enroller", "status0", "status1"):
            self.sql(
                f"ALTER ROLE {self.roles[name]} SET default_transaction_read_only = on"
            )
        owner = self.roles["owner"]
        self.sql(f"CREATE DATABASE {self.database} OWNER {owner}")
        self.sql(f"REVOKE ALL ON DATABASE {self.database} FROM PUBLIC")
        for name, role in self.roles.items():
            if name != "owner":
                self.sql(f"GRANT CONNECT ON DATABASE {self.database} TO {role}")
        self.sql(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {self.roles['app']}",
            self.database,
        )
        self.sql(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {self.roles['app']}",
            self.database,
        )

    def drop(self):
        self.sql(f"DROP DATABASE IF EXISTS {self.database} WITH (FORCE)")
        for role in self.roles.values():
            self.sql(f"DROP ROLE IF EXISTS {role}")

    def env(self, role="owner", **extra):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("KEEPLANE_", "DJANGO_", "GATEWAY_"))
        }
        env.update(
            PYTHONPATH=os.pathsep.join(
                [str(ROOT / "components/control-plane"), str(ROOT)]
            ),
            PYTHONDONTWRITEBYTECODE="1",
            DJANGO_SETTINGS_MODULE="config.settings",
            DJANGO_SECRET_KEY_FILE=str(self.files / "signing"),
            KEEPLANE_DATABASE_HOST=self.admin["host"],
            KEEPLANE_DATABASE_PORT=str(self.admin["port"]),
            KEEPLANE_DATABASE_NAME=self.database,
            KEEPLANE_DATABASE_USER=self.roles[role],
            KEEPLANE_DATABASE_PASSWORD_FILE=str(self.files / "password"),
            KEEPLANE_DATABASE_SSLMODE=self.admin["sslmode"],
            **extra,
        )
        return env

    def manage(self, *arguments, role="owner"):
        return subprocess.run(
            [sys.executable, str(ROOT / "components/control-plane/manage.py"), *arguments],
            env=self.env(role),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    def configure(self, *copies, role="owner", enroller="enroller"):
        copies = copies or (f"{COPY}={self.roles['status0']}", f"{OTHER}={self.roles['status1']}")
        arguments = ["configure_guard_status_access"]
        arguments += ["--app-role", self.roles["app"], "--enroller-role", self.roles[enroller]]
        for value in copies:
            arguments += ["--copy", value]
        return self.manage(*arguments, role=role)

    def connect(self, name, read_only=False):
        options = "-c default_transaction_read_only=on" if read_only else ""
        return self.psycopg.connect(
            **{
                **self.admin,
                "dbname": self.database,
                "user": self.roles[name],
                "password": self.password,
            },
            autocommit=True,
            options=options,
        )

    def attempt(self, name, *statements, read_write=False, values=None):
        """Run statements as a role; the error class name, or the last result."""
        with self.connect(name, read_only=True) as connection:
            try:
                if read_write:
                    connection.execute("BEGIN READ WRITE")
                result = None
                for statement in statements:
                    cursor = connection.execute(statement, values)
                    result = cursor.rowcount if cursor.description is None else cursor.fetchall()
                if read_write:
                    connection.execute("COMMIT")
                return result
            except self.psycopg.Error as error:
                return type(error).__name__


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    psycopg = pytest.importorskip("psycopg")
    if not os.environ.get(POSTGRES_ENV):
        pytest.skip("Set KEEPLANE_TEST_POSTGRES_* to a disposable PostgreSQL server")
    found = Cluster(psycopg, tmp_path_factory.mktemp("guard-status"))
    found.create()
    try:
        migrated = found.manage("migrate", "--noinput")
        assert migrated.returncode == 0, migrated.stderr[-2000:]
        found.sql(
            f"INSERT INTO {APPROVALS} (model_id, key_choice, approved_classes, "
            "gateway_fingerprint, owned_by_keeplane) "
            f"VALUES ('demo', 'none', '[]', '{'d' * 64}', false)",
            found.database,
        )
        yield found
    finally:
        found.drop()


def upsert(copy_name):
    return (
        f"INSERT INTO {TABLE} (copy_name, confirmed, declaration, confirmed_at, "
        f"updated_at) VALUES ('{copy_name}', false, NULL, NULL, now()) "
        "ON CONFLICT (copy_name) DO UPDATE SET updated_at = EXCLUDED.updated_at"
    )


def test_gs_pg_01_postgresql_after_migrate_the_app_cannot_write_the_status_table(cluster):
    # Before the installer runs the command, row-level security already
    # refuses every write from the app's default table grants.
    assert cluster.attempt("app", upsert(COPY), read_write=True) == "InsufficientPrivilege"
    assert cluster.attempt("app", f"SELECT copy_name FROM {TABLE}") == []


def test_gs_pg_02_postgresql_the_command_refuses_an_unsafe_setup(cluster):
    as_app = cluster.configure(role="app")
    assert as_app.returncode != 0 and "migration credential" in as_app.stderr
    # A role without read-only transactions by default is refused.
    loose = cluster.configure(f"{COPY}={cluster.roles['loose']}")
    assert loose.returncode != 0 and "default_transaction_read_only" in loose.stderr
    missing = cluster.configure(f"{COPY}=kgs_nobody_{uuid.uuid4().hex[:8]}")
    assert missing.returncode != 0 and "create these roles" in missing.stderr
    bad = cluster.configure(f"{COPY}")
    assert bad.returncode != 0 and "POD=ROLE" in bad.stderr


@pytest.mark.parametrize(
    "member, target", [("status0", "status1"), ("app", "status0"), ("enroller", "app")]
)
def test_gs_pg_10_postgresql_a_listed_role_may_not_belong_to_another(
    cluster, member, target
):
    # Even without inheriting privileges, a member could SET ROLE to the other.
    member_role, target_role = cluster.roles[member], cluster.roles[target]
    cluster.sql(f"ALTER ROLE {member_role} NOINHERIT")
    cluster.sql(f"GRANT {target_role} TO {member_role}")
    try:
        refused = cluster.configure()
        assert refused.returncode != 0
        assert f"{member_role} in {target_role}" in refused.stderr
    finally:
        cluster.sql(f"REVOKE {target_role} FROM {member_role}")
        cluster.sql(f"ALTER ROLE {member_role} INHERIT")
    assert cluster.configure().returncode == 0


def test_gs_pg_03_postgresql_the_command_is_idempotent(cluster):
    for _ in range(2):
        result = cluster.configure()
        assert result.returncode == 0, result.stderr[-2000:]
        assert "2 gateway copies" in result.stdout


def test_gs_pg_04_postgresql_a_status_role_writes_only_its_own_row(cluster):
    assert cluster.configure().returncode == 0
    # Read-only by default: a plain write fails even for its own row.
    assert cluster.attempt("status0", upsert(COPY)) == "ReadOnlySqlTransaction"
    # An explicit READ WRITE transaction writes its own row, again and again.
    assert cluster.attempt("status0", upsert(COPY), read_write=True) == 1
    assert cluster.attempt("status0", upsert(COPY), read_write=True) == 1
    # Another copy's row: neither inserted nor, once it exists, changed or read.
    assert cluster.attempt("status0", upsert(OTHER), read_write=True) == "InsufficientPrivilege"
    assert cluster.attempt("status1", upsert(OTHER), read_write=True) == 1
    assert cluster.attempt("status0", upsert(OTHER), read_write=True) == "InsufficientPrivilege"
    assert (
        cluster.attempt(
            "status0",
            f"UPDATE {TABLE} SET confirmed = false WHERE copy_name = '{OTHER}'",
            read_write=True,
        )
        == 0
    )
    assert cluster.attempt("status0", f"SELECT copy_name FROM {TABLE}") == [(COPY,)]
    # Renaming its own row into another copy's is refused too.
    assert (
        cluster.attempt(
            "status0",
            f"UPDATE {TABLE} SET copy_name = 'keeplane-gateway-9' WHERE copy_name = '{COPY}'",
            read_write=True,
        )
        == "InsufficientPrivilege"
    )
    assert (
        cluster.attempt(
            "status0", f"DELETE FROM {TABLE} WHERE copy_name = '{COPY}'", read_write=True
        )
        == "InsufficientPrivilege"
    )


@pytest.mark.parametrize("role", ["status0", "enroller"])
def test_gs_pg_05_postgresql_enroller_roles_cannot_touch_other_tables(cluster, role):
    assert cluster.configure().returncode == 0
    for statement in (
        "SELECT id FROM accounts_user",
        "SELECT id FROM django_migrations",
        f"INSERT INTO {APPROVALS} (model_id, key_choice, approved_classes, "
        "gateway_fingerprint, owned_by_keeplane) VALUES ('x', 'none', '[]', 'x', false)",
    ):
        assert cluster.attempt(role, statement, read_write=True) == "InsufficientPrivilege"
    if role == "status0":
        assert cluster.attempt(role, f"SELECT model_id FROM {APPROVALS}") == (
            "InsufficientPrivilege"
        )


def test_gs_pg_06_postgresql_the_approvals_connection_cannot_write(cluster):
    assert cluster.configure().returncode == 0
    assert cluster.attempt("enroller", f"SELECT model_id FROM {APPROVALS}") == [("demo",)]
    # Read-only by default, and without any write grant even when asked.
    update = f"UPDATE {APPROVALS} SET approved_classes = '[\"x\"]'"
    assert cluster.attempt("enroller", update) == "ReadOnlySqlTransaction"
    assert cluster.attempt("enroller", update, read_write=True) == "InsufficientPrivilege"
    assert cluster.attempt("enroller", f"SELECT copy_name FROM {TABLE}") == (
        "InsufficientPrivilege"
    )
    assert cluster.attempt("enroller", upsert(COPY), read_write=True) == (
        "InsufficientPrivilege"
    )


def test_gs_pg_07_postgresql_the_app_only_reads_the_status_table(cluster):
    assert cluster.configure().returncode == 0
    assert cluster.attempt("status0", upsert(COPY), read_write=True) == 1
    assert cluster.attempt("status1", upsert(OTHER), read_write=True) == 1
    assert sorted(cluster.attempt("app", f"SELECT copy_name FROM {TABLE}")) == [
        (COPY,),
        (OTHER,),
    ]
    for statement in (
        upsert("keeplane-gateway-5"),
        f"UPDATE {TABLE} SET confirmed = false",
        f"DELETE FROM {TABLE}",
        f"TRUNCATE {TABLE}",
    ):
        assert cluster.attempt("app", statement, read_write=True) == "InsufficientPrivilege"


def test_gs_pg_08_postgresql_a_copy_left_out_loses_its_access(cluster):
    assert cluster.configure().returncode == 0
    assert cluster.attempt("status1", upsert(OTHER), read_write=True) == 1
    assert cluster.configure(f"{COPY}={cluster.roles['status0']}").returncode == 0
    assert cluster.attempt("status1", upsert(OTHER), read_write=True) == "InsufficientPrivilege"
    assert cluster.attempt("status0", upsert(COPY), read_write=True) == 1
    assert cluster.configure().returncode == 0


PROBE = """
import json, django
django.setup()
from model_registry.management.commands.run_model_enroller import guard_status_recorder
from model_registry.guard_status import GuardStatusRecorder
from model_registry.models import ModelApproval
declaration = json.loads({declaration!r})
result = {{}}
name, recorder = guard_status_recorder()
result["copy"] = name
recorder.confirm(declaration)
result["confirmed"] = recorder.current() == (True, declaration)
recorder.clear()
result["cleared"] = recorder.current() == (False, None)
recorder.confirm(declaration)
try:
    GuardStatusRecorder({other!r}).confirm(declaration)
    result["other"] = "written"
except Exception as error:
    result["other"] = type(error).__name__
try:
    ModelApproval.objects.filter(pk="demo").update(approved_classes=["x"])
    result["approval"] = "written"
except Exception as error:
    result["approval"] = type(error).__name__
result["approvals_read"] = list(ModelApproval.objects.values_list("model_id", flat=True))
print(json.dumps(result))
"""

APP_PROBE = """
import json, django
django.setup()
from model_registry.guard_status import copy_declaration
from model_registry.models import GatewayGuardStatus
result = {{"models": list(copy_declaration({copy!r})()["models"])}}
try:
    copy_declaration({other!r})()
    result["other"] = "confirmed"
except Exception as error:
    result["other"] = type(error).__name__
try:
    GatewayGuardStatus.objects.filter(pk={copy!r}).update(confirmed=False)
    result["write"] = "written"
except Exception as error:
    result["write"] = type(error).__name__
print(json.dumps(result))
"""


def run_probe(cluster, probe, env):
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_gs_pg_09_postgresql_the_enroller_records_its_copy_and_the_app_reads_it(cluster):
    assert cluster.configure().returncode == 0
    cluster.sql(f"DELETE FROM {TABLE}", cluster.database)
    enroller = cluster.env(
        "enroller",
        KEEPLANE_DATABASE_READ_ONLY="1",
        KEEPLANE_GATEWAY_COPY=COPY,
        KEEPLANE_GUARD_STATUS_DATABASE_USER=cluster.roles["status0"],
        KEEPLANE_GUARD_STATUS_DATABASE_PASSWORD_FILE=str(cluster.files / "password"),
    )
    found = run_probe(
        cluster,
        PROBE.format(declaration=json.dumps(DECLARATION), other=OTHER),
        enroller,
    )
    assert found == {
        "copy": COPY,
        "confirmed": True,
        "cleared": True,
        # Row-level security refuses the other copy's row.
        "other": "StorageUnavailable",
        # A read-only transaction (Django's InternalError) on the approvals.
        "approval": "InternalError",
        "approvals_read": ["demo"],
    }
    app = run_probe(
        cluster,
        APP_PROBE.format(copy=COPY, other=OTHER),
        cluster.env("app"),
    )
    assert app == {
        "models": ["demo"],
        "other": "ModelPolicyUnavailable",
        "write": "ProgrammingError",  # permission denied
    }


# --- check_credentials reports the guard-status roles (002-02, 004-01) ---

COPY_URLS = f"http://{COPY}.gateway.test:15000,http://{OTHER}.gateway.test:15000"
RERUN = "; run configure_guard_status_access again"
REPORT_PROBE = """
import json, django
django.setup()
from common.api import MODEL_GATEWAY_COPIES
from common.credential_check import guard_status_report
report, problems, warnings = guard_status_report(MODEL_GATEWAY_COPIES.copies)
print(json.dumps({"report": report, "problems": problems, "warnings": warnings}))
"""


def guard_report(cluster, check="1"):
    env = cluster.env("app", KEEPLANE_GUARD_STATUS_CHECK=check, GATEWAY_COPY_URLS=COPY_URLS)
    return run_probe(cluster, REPORT_PROBE, env)


def copy_entry(report, name):
    return next(entry for entry in report["copies"] if entry["copy"] == name)


def not_paired(name):
    return f"Gateway copy {name}: no status role is paired with it{RERUN} with --copy {name}=<role>"


@pytest.fixture
def reported(cluster):
    """Both copies paired as the guide sets them; copy 0 confirmed, copy 1 not."""
    assert cluster.configure().returncode == 0
    cluster.sql(f"DELETE FROM {TABLE}", cluster.database)
    cluster.sql(
        f"INSERT INTO {TABLE} (copy_name, confirmed, declaration, confirmed_at, "
        f"updated_at) VALUES ('{COPY}', true, '{json.dumps(DECLARATION)}', "
        "now() - interval '90 minutes', now() - interval '90 minutes'), "
        f"('{OTHER}', false, NULL, NULL, now())",
        cluster.database,
    )
    yield cluster
    assert cluster.configure().returncode == 0


def test_gs_pg_11_postgresql_check_credentials_reports_each_copy_role_and_guard(reported):
    found = guard_report(reported)
    assert found["problems"] == []
    assert found["warnings"] == [
        f"Gateway copy {OTHER}: no guard is confirmed; protected models are refused "
        "through it until its enroller confirms one"
    ]
    report = found["report"]
    assert {key: report[key] for key in ("row_security", "policies", "app_role")} == {
        "row_security": "on",
        "policies": "as set",
        "app_role": "reads only",
    }
    first = copy_entry(report, COPY)
    assert first["status_role"] == reported.roles["status0"]
    assert first["role_status"] == "limited"
    assert first["guard"] == "confirmed"
    assert 89 <= first["age_minutes"] <= 95
    assert first["models"] == [{"id": "demo", "fingerprint": "d" * 64}]
    second = copy_entry(report, OTHER)
    assert (second["status_role"], second["role_status"], second["guard"]) == (
        reported.roles["status1"],
        "limited",
        "not confirmed",
    )
    assert "models" not in second and "confirmed_at" not in second
    # No password and none of the declaration's digests is printed.
    text = json.dumps(found)
    assert reported.password not in text
    assert not any(letter * 64 in text for letter in "abc")


# fault: (change, undo, role status, the problem after "its status role <role>")
UNSAFE = {
    "bypasses row security": (
        "ALTER ROLE {status0} BYPASSRLS",
        "ALTER ROLE {status0} NOBYPASSRLS",
        "unsafe",
        " is a superuser, can bypass row-level security or can create roles",
    ),
    "creates roles": (
        "ALTER ROLE {status0} CREATEROLE",
        "ALTER ROLE {status0} NOCREATEROLE",
        "unsafe",
        " is a superuser, can bypass row-level security or can create roles",
    ),
    "member of the migration role": (
        "GRANT {owner} TO {status0}",
        "REVOKE {owner} FROM {status0}",
        "unsafe",
        " is a member of the migration role {owner}",
    ),
    "member of the other copy's role": (
        "GRANT {status1} TO {status0}",
        "REVOKE {status1} FROM {status0}",
        "unsafe",
        " belongs to {status1}; revoke the membership",
    ),
    "not read-only by default": (
        "ALTER ROLE {status0} RESET default_transaction_read_only",
        "ALTER ROLE {status0} SET default_transaction_read_only = on",
        "unsafe",
        " doesn't have default_transaction_read_only = on",
    ),
    "reads another table": (
        "GRANT SELECT ON accounts_user TO {status0}",
        "REVOKE SELECT ON accounts_user FROM {status0}",
        "unsafe",
        " has more access than allowed: SELECT on accounts_user",
    ),
    "deletes rows": (
        f"GRANT DELETE ON {TABLE} TO {{status0}}",
        f"REVOKE DELETE ON {TABLE} FROM {{status0}}",
        "unsafe",
        f" has more access than allowed: DELETE on {TABLE}",
    ),
    "no login": (
        "ALTER ROLE {status0} NOLOGIN",
        "ALTER ROLE {status0} LOGIN",
        "cannot log in",
        " can't log in (NOLOGIN)",
    ),
    "password expired": (
        "ALTER ROLE {status0} VALID UNTIL '2001-01-01'",
        "ALTER ROLE {status0} VALID UNTIL 'infinity'",
        "cannot log in",
        "'s password has expired (VALID UNTIL)",
    ),
    "no connect": (
        "REVOKE CONNECT ON DATABASE {database} FROM {status0}",
        "GRANT CONNECT ON DATABASE {database} TO {status0}",
        "cannot log in",
        " has no CONNECT on the database",
    ),
}


@pytest.mark.parametrize("fault", sorted(UNSAFE))
def test_gs_pg_12_postgresql_check_credentials_fails_on_an_unsafe_status_role(
    reported, fault
):
    change, undo, state, sentence = UNSAFE[fault]
    names = {
        **{name: reported.roles[name] for name in ("owner", "status0", "status1")},
        "database": reported.database,
    }
    reported.sql(change.format(**names), reported.database)
    try:
        found = guard_report(reported)
    finally:
        reported.sql(undo.format(**names), reported.database)
    assert copy_entry(found["report"], COPY)["role_status"] == state
    assert copy_entry(found["report"], OTHER)["role_status"] == "limited"
    prefix = f"Gateway copy {COPY}: its status role {names['status0']}"
    problems = found["problems"]
    assert problems[0] == prefix + sentence.format(**names)
    if fault == "member of the migration role":
        # It inherits the owner's privileges, which are summarised, not listed.
        assert problems[1].startswith(prefix + " has more access than allowed: ")
        assert re.search(r" and \d+ more$", problems[1])
        assert len(problems) == 2
    else:
        assert len(problems) == 1
    assert guard_report(reported)["problems"] == []


def test_gs_pg_12_postgresql_check_credentials_fails_when_the_app_can_write(reported):
    app = reported.roles["app"]
    reported.sql(f"GRANT INSERT, DELETE ON {TABLE} TO {app}", reported.database)
    found = guard_report(reported)
    assert found["report"]["app_role"] == "unsafe"
    assert found["problems"] == [
        f"Guard status: The app role {app} has more access than allowed: "
        f"DELETE on {TABLE}, INSERT on {TABLE}",
    ]


@pytest.mark.parametrize(
    "fault", ["row security off", "extra policy", "copy left out", "stale pairing", "no row"]
)
def test_gs_pg_13_postgresql_check_credentials_fails_on_a_changed_setup(reported, fault):
    status0, status1 = reported.roles["status0"], reported.roles["status1"]
    if fault == "row security off":
        reported.sql(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY", reported.database)
    elif fault == "extra policy":
        reported.sql(
            f"CREATE POLICY anyone ON {TABLE} FOR ALL TO {status1} USING (true)",
            reported.database,
        )
    elif fault == "copy left out":
        assert reported.configure(f"{COPY}={status0}").returncode == 0
    elif fault == "stale pairing":
        assert reported.configure(
            f"{COPY}={status0}", f"keeplane-gateway-7={status1}"
        ).returncode == 0
    else:
        reported.sql(f"DELETE FROM {TABLE} WHERE copy_name = '{OTHER}'", reported.database)
    try:
        found = guard_report(reported)
    finally:
        reported.sql(f"DROP POLICY IF EXISTS anyone ON {TABLE}", reported.database)
    assert found["problems"] == {
        "row security off": [
            "Guard status: row-level security is off for the guard-status table" + RERUN
        ],
        "extra policy": [
            "Guard status: the guard-status table's policies aren't the ones "
            "configure_guard_status_access sets" + RERUN,
            not_paired(COPY),
            not_paired(OTHER),
        ],
        "copy left out": [not_paired(OTHER)],
        "stale pairing": [not_paired(OTHER)],
        "no row": [f"Gateway copy {OTHER}: its enroller has recorded no guard status yet"],
    }[fault]
    report = found["report"]
    if fault == "stale pairing":
        assert found["warnings"][-1] == (
            f"Guard status: status role {status1} is still paired with "
            "keeplane-gateway-7, which isn't in the gateway copy list" + RERUN
            + " to remove its access"
        )
    if fault == "no row":
        assert copy_entry(report, OTHER)["guard"] == "not recorded"
    if fault == "row security off":
        assert report["row_security"] == "off"
    if fault == "extra policy":
        assert report["policies"] == "changed"
        assert copy_entry(report, COPY)["role_status"] == "not paired"


def test_gs_pg_14_postgresql_the_command_exits_1_and_prints_no_secret(reported):
    status0 = reported.roles["status0"]
    reported.sql(f"ALTER ROLE {status0} BYPASSRLS", reported.database)
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "components/control-plane/manage.py"),
             "check_credentials"],
            env=reported.env(
                "app",
                KEEPLANE_GUARD_STATUS_CHECK="1",
                GATEWAY_COPY_URLS=COPY_URLS,
                GATEWAY_URL="http://127.0.0.1:9",
            ),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    finally:
        reported.sql(f"ALTER ROLE {status0} NOBYPASSRLS", reported.database)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["passed"] is False
    assert copy_entry(report["guard_status"], COPY)["role_status"] == "unsafe"
    assert len(report["guard_status_problems"]) == 1
    assert reported.password not in result.stdout + result.stderr
    # With the per-copy check off the same database reports "not in use".
    assert guard_report(reported, check="0") == {
        "report": "not in use",
        "problems": [],
        "warnings": [],
    }
