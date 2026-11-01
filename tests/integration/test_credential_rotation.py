"""Rotating Keeplane's installation credentials keeps models and approvals.

Spec 002 ST3-ST5, task 002-02 credential rotation. The plain-English cases are
in credential-rotation-cases.md. Each control-plane process runs on its own,
as a pod does, and the test changes its mounted credential files under it the
way Kubernetes updates a mounted Secret.
"""

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.integration import test_audit_persistence as persistence

ROOT = Path(__file__).resolve().parents[2]
PROCESS = ROOT / "tests/fixtures/credential_rotation_process.py"
POSTGRES_ENV = persistence.POSTGRES_ENV
KEEPLANE_MODEL = {"id": "keeplane-model", "revision": 3,
                  "value": {"name": "keeplane-model", "params": {"model": "a"}}}
CUSTOMER_MODEL = {"id": "customer-model", "revision": 7,
                  "value": {"name": "customer-model", "params": {"model": "b"}}}


def new_key():
    return secrets.token_urlsafe(32)


def key_hash(key):
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()


class Gateway:
    """One gateway copy holding the key hashes it loaded when it started.

    Management (/api/) needs the admin key and model calls (/v1/) the runtime
    key, as the chart's two strict key policies do. During a rotation each
    policy may also hold the next key's hash (the chart's optional
    *_KEY_HASH_NEXT). Its model store is shared by every copy and is never
    touched by a key change.
    """

    store = None

    def __init__(self, store, runtime_key, admin_key):
        self.store = store
        self.load(runtime_key, admin_key)
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                admin = self.path.startswith("/api/")
                accepted = gateway.admin_hashes if admin else gateway.runtime_hashes
                supplied = self.headers.get("Authorization", "")
                if not supplied.startswith("Bearer ") or key_hash(supplied[7:]) not in accepted:
                    return self.answer(401, {"error": "authentication failure"})
                if self.path == "/api/runtime":
                    return self.answer(200, {"build": {"version": "1.6.0"}})
                if self.path == "/api/config/resources/llm.model":
                    return self.answer(200, {"resources": json.loads(json.dumps(gateway.store))})
                if self.path == "/v1/models":
                    return self.answer(200, {"data": [{"id": row["id"]} for row in gateway.store]})
                return self.answer(404, {"error": "not found"})

            def answer(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def load(self, runtime_key, admin_key, runtime_next=None, admin_next=None):
        """What a restart does: read the key hashes from the Secret again."""
        self.runtime_hash, self.admin_hash = key_hash(runtime_key), key_hash(admin_key)
        self.runtime_hashes = {self.runtime_hash, *([key_hash(runtime_next)] if runtime_next else [])}
        self.admin_hashes = {self.admin_hash, *([key_hash(admin_next)] if admin_next else [])}

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class AppProcess(persistence.AppProcess):
    def __init__(self, env):
        self.child = subprocess.Popen(
            [sys.executable, str(PROCESS)], cwd=ROOT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )


class Installation:
    """Mounted credential files, gateway copies and app processes."""

    def __init__(self, tmp_path, database):
        self.files = tmp_path / "mounted"
        self.files.mkdir()
        self.runtime_key, self.admin_key = new_key(), new_key()
        self.write("runtime-key", self.runtime_key)
        self.write("admin-key", self.admin_key)
        self.write("signing-secret", secrets.token_urlsafe(48))
        self.write("first-admin-password", secrets.token_urlsafe(24))
        self.store = [json.loads(json.dumps(KEEPLANE_MODEL)), json.loads(json.dumps(CUSTOMER_MODEL))]
        self.copies = [Gateway(self.store, self.runtime_key, self.admin_key) for _ in range(2)]
        self.database = database
        self.processes = []

    def write(self, name, value):
        # Kubernetes swaps the whole file; a reader never sees half a value.
        target = self.files / name
        staged = self.files / (name + ".new")
        staged.write_text(value + "\n")
        staged.replace(target)

    def env(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("KEEPLANE_", "DJANGO_", "GATEWAY_"))}
        env.update(
            self.database,
            PYTHONPATH=os.pathsep.join([str(ROOT / "components/control-plane"), str(ROOT)]),
            PYTHONDONTWRITEBYTECODE="1",
            DJANGO_SETTINGS_MODULE="config.settings",
            DJANGO_SECRET_KEY_FILE=str(self.files / "signing-secret"),
            FIRST_ADMIN_PASSWORD_FILE=str(self.files / "first-admin-password"),
            GATEWAY_URL=self.copies[0].url,
            GATEWAY_MODE="managed",
            GATEWAY_COPY_URLS=",".join(copy.url for copy in self.copies),
            GATEWAY_RUNTIME_KEY_FILE=str(self.files / "runtime-key"),
            GATEWAY_ADMIN_KEY_FILE=str(self.files / "admin-key"),
        )
        return env

    def start(self):
        process = AppProcess(self.env())
        self.processes.append(process)
        return process

    def fingerprints(self):
        from model_registry.fingerprints import fingerprint

        return {row["id"]: fingerprint(row["id"], self.store) for row in self.store}

    def stop(self):
        for process in self.processes:
            process.stop()
        for copy in self.copies:
            copy.stop()


# SQLite always; PostgreSQL when KEEPLANE_TEST_POSTGRES_* is set (CI).
database = persistence.database


@pytest.fixture
def installation(database, tmp_path):
    found = Installation(tmp_path, database)
    yield found
    found.stop()


def installed(installation):
    app = installation.start()
    app.ask("migrate")
    before = app.ask("set_up", fingerprints=installation.fingerprints())
    return app, before


def report_lists(result):
    return result["report"]["gateway_models"], result["report"]["approvals"]


def test_cr_01_gateway_keys_rotate_without_an_app_restart(installation):
    app, before = installed(installation)
    first = app.ask("check_credentials")
    assert first["exit"] == 0 and first["report"]["passed"] is True
    models_before = report_lists(first)
    assert [row["id"] for row in models_before[0]] == ["customer-model", "keeplane-model"]
    store_before = json.loads(json.dumps(installation.store))

    runtime_key, admin_key = new_key(), new_key()
    installation.write("runtime-key", runtime_key)
    installation.write("admin-key", admin_key)
    for copy in installation.copies:
        copy.load(runtime_key, admin_key)

    assert app.ask("gateway") == {
        "runtime_status": 200, "runtime_error": None, "models_status": 200,
    }
    after = app.ask("check_credentials")
    assert after["exit"] == 0
    assert report_lists(after) == models_before
    assert installation.store == store_before
    assert app.ask("database") == {"ok": True, "snapshot": before}
    # The old keys no longer open anything.
    for copy in installation.copies:
        assert copy.admin_hash != key_hash(installation.admin_key)
        assert copy.runtime_hash != key_hash(installation.runtime_key)


def test_cr_02_a_half_done_gateway_rotation_is_reported_not_hidden(installation):
    app, before = installed(installation)
    runtime_key, admin_key = new_key(), new_key()
    installation.write("runtime-key", runtime_key)
    installation.write("admin-key", admin_key)
    # Only the second copy has restarted with the new hashes.
    installation.copies[1].load(runtime_key, admin_key)

    seen = app.ask("gateway")
    assert seen["runtime_status"] == 503
    assert seen["runtime_error"].startswith("The gateway refused Keeplane's admin key.")
    assert seen["models_status"] == 401
    assert any("refused Keeplane's admin key" in line for line in app.ask("logged")["logged"])
    half = app.ask("check_credentials")
    assert half["exit"] == 1 and half["report"]["passed"] is False
    assert [(row["admin_key"], row["runtime_key"]) for row in half["report"]["gateway"]] == [
        ("refused", "refused"), ("accepted", "accepted"),
    ]
    assert half["report"]["gateway"][1]["address"] == installation.copies[1].url
    for secret in (runtime_key, admin_key, key_hash(admin_key)):
        assert secret not in json.dumps(half)

    installation.copies[0].load(runtime_key, admin_key)
    done = app.ask("check_credentials")
    assert done["exit"] == 0
    assert app.ask("database") == {"ok": True, "snapshot": before}


def answers(copy, path, key):
    """The status a gateway copy gives one key, as the app's adapter sends it."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    request = Request(copy.url + path, headers={"Authorization": "Bearer " + key})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status
    except HTTPError as error:
        return error.code


def next_answers(result):
    return [(row.get("admin_key_next"), row.get("runtime_key_next"))
            for row in result["report"]["gateway"]]


def test_cr_11_overlapping_gateway_rotation_refuses_no_call(installation):
    app, before = installed(installation)
    first = app.ask("check_credentials")
    assert first["exit"] == 0 and next_answers(first) == [(None, None), (None, None)]
    models_before = report_lists(first)
    old_runtime, old_admin = installation.runtime_key, installation.admin_key
    runtime_key, admin_key = new_key(), new_key()
    every_call = []

    def calls_succeed():
        """The app's own calls, and the keys it holds now on every copy."""
        seen = app.ask("gateway")
        every_call.append(seen)
        held = {name: (installation.files / name).read_text().strip()
                for name in ("admin-key", "runtime-key")}
        return seen == {
            "runtime_status": 200, "runtime_error": None, "models_status": 200,
        } and all(
            answers(copy, "/api/runtime", held["admin-key"]) == 200
            and answers(copy, "/v1/models", held["runtime-key"]) == 200
            for copy in installation.copies
        )

    # Step 1: the next keys go into the Secret beside the current ones, and the
    # copies restart one at a time accepting both.
    installation.write("runtime-key-next", runtime_key)
    installation.write("admin-key-next", admin_key)
    installation.copies[1].load(old_runtime, old_admin, runtime_key, admin_key)
    assert calls_succeed()
    half = app.ask("check_credentials")
    assert half["exit"] == 1 and half["report"]["passed"] is False
    assert next_answers(half) == [("refused", "refused"), ("accepted", "accepted")]
    assert [(row["admin_key"], row["runtime_key"]) for row in half["report"]["gateway"]] == [
        ("accepted", "accepted"), ("accepted", "accepted"),
    ]
    installation.copies[0].load(old_runtime, old_admin, runtime_key, admin_key)
    assert calls_succeed()
    ready = app.ask("check_credentials")
    assert ready["exit"] == 0
    assert next_answers(ready) == [("accepted", "accepted"), ("accepted", "accepted")]

    # Step 2: Keeplane switches to the next keys. Both keys open every copy.
    installation.write("runtime-key", runtime_key)
    installation.write("admin-key", admin_key)
    assert calls_succeed()
    assert app.ask("check_credentials")["exit"] == 0

    # Step 3: the next keys become the only keys; the copies restart one at a
    # time, then the next entries leave the Secret.
    installation.copies[1].load(runtime_key, admin_key)
    assert calls_succeed()
    installation.copies[0].load(runtime_key, admin_key)
    assert calls_succeed()
    for name in ("runtime-key-next", "admin-key-next"):
        (installation.files / name).unlink()
    after = app.ask("check_credentials")
    assert after["exit"] == 0 and next_answers(after) == [(None, None), (None, None)]

    assert all(call["models_status"] == 200 for call in every_call)
    assert report_lists(after) == models_before
    assert app.ask("database") == {"ok": True, "snapshot": before}
    # The old keys open nothing, and no report holds a key or key hash.
    for copy in installation.copies:
        assert answers(copy, "/api/runtime", old_admin) == 401
        assert answers(copy, "/v1/models", old_runtime) == 401
    reports = json.dumps([first, half, ready, after])
    for secret in (old_runtime, old_admin, runtime_key, admin_key):
        assert secret not in reports and key_hash(secret) not in reports


def test_cr_12_a_wrong_next_key_is_caught_before_the_switch(installation):
    app, _ = installed(installation)
    runtime_key, admin_key = new_key(), new_key()
    installation.write("runtime-key-next", runtime_key)
    installation.write("admin-key-next", admin_key)
    # The copies loaded a next hash made from a different admin key.
    for copy in installation.copies:
        copy.load(installation.runtime_key, installation.admin_key, runtime_key, new_key())
    result = app.ask("check_credentials")
    assert result["exit"] == 1
    assert next_answers(result) == [("refused", "accepted"), ("refused", "accepted")]
    # Keeplane itself still works on its current keys.
    assert app.ask("gateway")["models_status"] == 200


def test_cr_03_signing_secret_rotation_signs_everyone_out_and_keeps_settings(installation):
    app, before = installed(installation)
    token = app.ask("sign_in")["token"]
    assert app.ask("session", token=token) == {"username": "first-admin"}
    after_sign_in = app.ask("database")["snapshot"]

    # Same secret, new process: a restart alone keeps the session.
    app.stop()
    restarted = installation.start()
    assert restarted.ask("session", token=token) == {"username": "first-admin"}
    restarted.stop()

    installation.write("signing-secret", secrets.token_urlsafe(48))
    # A running process keeps the secret it started with until it restarts.
    rotated = installation.start()
    assert rotated.ask("session", token=token) == {"username": None}
    assert rotated.ask("database") == {"ok": True, "snapshot": after_sign_in}
    assert after_sign_in["approvals"] == before["approvals"]
    new_token = rotated.ask("sign_in")["token"]
    assert rotated.ask("session", token=new_token) == {"username": "first-admin"}
    assert rotated.ask("check_credentials")["exit"] == 0


# --- PostgreSQL role passwords --------------------------------------------


@contextmanager
def postgres_role():
    """A disposable login role that owns a disposable database."""
    psycopg = pytest.importorskip("psycopg")
    if not os.environ.get(POSTGRES_ENV):
        pytest.skip("Set KEEPLANE_TEST_POSTGRES_* to a disposable PostgreSQL server")
    suffix = uuid.uuid4().hex[:12]
    role, name, first = "keeplane_rotation_" + suffix, "keeplane_rotation_" + suffix, new_key()
    target = {
        "host": os.environ[POSTGRES_ENV],
        "port": os.environ.get("KEEPLANE_TEST_POSTGRES_PORT", "5432"),
        "user": os.environ["KEEPLANE_TEST_POSTGRES_USER"],
        "password": Path(os.environ["KEEPLANE_TEST_POSTGRES_PASSWORD_FILE"]).read_text().strip(),
        "dbname": os.environ.get("KEEPLANE_TEST_POSTGRES_NAME", "postgres"),
        "sslmode": os.environ.get("KEEPLANE_TEST_POSTGRES_SSLMODE", "disable"),
    }

    def as_admin(statement, value=None):
        with psycopg.connect(**target, autocommit=True) as admin:
            admin.execute(psycopg.sql.SQL(statement).format(
                role=psycopg.sql.Identifier(role), name=psycopg.sql.Identifier(name),
                value=psycopg.sql.Literal(value),
            ))

    def accepts(password):
        try:
            psycopg.connect(**{**target, "user": role, "dbname": name, "password": password}).close()
        except psycopg.OperationalError:
            return False
        return True

    as_admin("CREATE ROLE {role} LOGIN PASSWORD {value}", first)
    try:
        as_admin("CREATE DATABASE {name} OWNER {role}")
        try:
            yield {
                "database": {
                    "KEEPLANE_DATABASE_HOST": target["host"],
                    "KEEPLANE_DATABASE_PORT": target["port"],
                    "KEEPLANE_DATABASE_NAME": name,
                    "KEEPLANE_DATABASE_USER": role,
                    "KEEPLANE_DATABASE_SSLMODE": target["sslmode"],
                },
                "first": first,
                "set_password": lambda value: as_admin(
                    "ALTER ROLE {role} PASSWORD {value}", value
                ),
                "accepts": accepts,
            }
        finally:
            as_admin("DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    finally:
        as_admin("DROP ROLE IF EXISTS {role}")


@pytest.fixture(params=["postgresql"])
def role_installation(request, tmp_path):
    with postgres_role() as role:
        found = Installation(tmp_path, {})
        found.write("database-password", role["first"])
        found.database = dict(
            role["database"],
            KEEPLANE_DATABASE_PASSWORD_FILE=str(found.files / "database-password"),
        )
        try:
            yield found, role
        finally:
            found.stop()


def test_cr_04_postgresql_password_rotates_in_order_without_refused_requests(role_installation):
    installation, role = role_installation
    app, before = installed(installation)
    second = new_key()

    # 1. The Secret gets the new password; the role still has the old one.
    installation.write("database-password", second)
    assert app.ask("database") == {"ok": True, "snapshot": before}
    assert app.ask("password_state") == {"previous_in_use": True}
    report = app.ask("check_credentials")
    assert report["exit"] == 1
    assert report["report"]["database"].startswith("connected with the previous password")
    # A new process, as `kubectl exec ... check_credentials` starts, has no
    # previous password: it reports the refusal plainly, not "unreachable".
    fresh = installation.start().ask("check_credentials")
    assert fresh["exit"] == 1
    assert fresh["report"]["database"] == "the database refuses the mounted password"

    # 2. The role's password changes; the running process follows at once.
    role["set_password"](second)
    assert app.ask("database") == {"ok": True, "snapshot": before}
    assert app.ask("password_state") == {"previous_in_use": False}
    assert app.ask("check_credentials")["exit"] == 0
    assert role["accepts"](second) and not role["accepts"](role["first"])
    logged = app.ask("logged")["logged"]
    assert any("still using the previous password" in line for line in logged)
    assert any("accepted the password in the mounted file" in line for line in logged)
    assert not any(role["first"] in line or second in line for line in logged)

    # 3. A restarted copy starts with the new password and sees the same settings.
    assert installation.start().ask("database") == {"ok": True, "snapshot": before}


def test_cr_05_role_changed_before_the_secret_recovers_without_a_restart(role_installation):
    installation, role = role_installation
    app, before = installed(installation)
    second = new_key()

    role["set_password"](second)
    assert app.ask("database")["ok"] is False
    installation.write("database-password", second)
    assert app.ask("database") == {"ok": True, "snapshot": before}
    assert app.ask("check_credentials")["exit"] == 0


def test_cr_06_a_wrong_password_in_the_secret_keeps_the_app_on_the_working_one(role_installation):
    installation, role = role_installation
    app, before = installed(installation)

    installation.write("database-password", "typo-" + new_key())
    for _ in range(3):
        assert app.ask("database") == {"ok": True, "snapshot": before}
    assert app.ask("check_credentials")["exit"] == 1
    assert sum("still using the previous password" in line
               for line in app.ask("logged")["logged"]) == 1
    # What the installer's `kubectl exec` check shows meanwhile.
    fresh = installation.start().ask("check_credentials")
    assert fresh["report"]["database"] == "the database refuses the mounted password"
    # Recovery: put the working password back.
    installation.write("database-password", role["first"])
    assert app.ask("database") == {"ok": True, "snapshot": before}
    assert app.ask("check_credentials")["exit"] == 0


def test_cr_10_an_unreachable_database_is_not_reported_as_a_refused_password(role_installation):
    import socket

    installation, _ = role_installation
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = str(probe.getsockname()[1])
    installation.database = dict(
        installation.database, KEEPLANE_DATABASE_HOST="127.0.0.1", KEEPLANE_DATABASE_PORT=closed
    )
    report = installation.start().ask("check_credentials")
    assert report["exit"] == 1
    assert report["report"]["database"] == "unreachable"


# --- How each credential reaches the pods (Helm render) --------------------


@pytest.fixture(scope="module")
def chart():
    """Rendered chart helpers; skips without Helm, as the other chart checks do."""
    from tests.integration import test_chart_installation_shape as shape

    return shape


CREDENTIAL_MOUNTS = {
    "database-credentials": "/run/keeplane-database",
    "database-ca": "/run/keeplane-database-ca",
    "identity": "/run/keeplane-identity",
    "gateway-keys": "/run/gateway-keys",
}
FILE_ENV = {
    "KEEPLANE_DATABASE_PASSWORD_FILE": "/run/keeplane-database/password",
    "KEEPLANE_DATABASE_SSLROOTCERT_FILE": "/run/keeplane-database-ca/ca.crt",
    "DJANGO_SECRET_KEY_FILE": "/run/keeplane-identity/signing-secret",
    "FIRST_ADMIN_PASSWORD_FILE": "/run/keeplane-identity/first-admin-password",
    "GATEWAY_RUNTIME_KEY_FILE": "/run/gateway-keys/runtime-key",
    "GATEWAY_ADMIN_KEY_FILE": "/run/gateway-keys/admin-key",
}


def render(chart, mode, tmp_path):
    values = tmp_path / ("values-" + mode + ".json")
    values.write_text(json.dumps(chart.postgres_values(mode)))
    result = chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                       "-f", str(values))
    assert result.returncode == 0, result.stderr
    return result.stdout


def workload(chart, output, kind, name):
    return next(doc for doc in chart.of_kind(output, kind) if chart.name_of(doc) == name)


@pytest.mark.parametrize("mode", ["managed", "existing"])
def test_cr_07_app_reads_every_credential_from_a_secret_file(chart, mode, tmp_path):
    output = render(chart, mode, tmp_path)
    app = workload(chart, output, "Deployment", "keeplane-app")
    container = next(item for item in chart.containers(app) if chart.scalar(item, "name") == "app")
    assert "subPath" not in app, "a subPath mount never receives a rotated Secret"
    variables = chart.env(container)
    for name, path in FILE_ENV.items():
        assert (name, path, False) in variables
    # No credential is handed over as a literal value or env from a Secret.
    for name, value, from_secret in variables:
        if chart.SENSITIVE.search(name) and not name.endswith(("_FILE", "_DIR")):
            pytest.fail(f"{name} carries a credential outside a mounted file")
        assert not from_secret
    mounted = {name: (path, read_only) for name, path, read_only in chart.mounts(container)}
    sources = chart.volumes(app)
    expected = {
        "database-credentials": "keeplane-app-db",
        "database-ca": "keeplane-database-ca",
        "identity": "keeplane-identity",
        "gateway-keys": "keeplane-gateway-keys",
    }
    for volume, secret in expected.items():
        assert mounted[volume] == (CREDENTIAL_MOUNTS[volume], True)
        assert sources[volume] == ("secret", secret)
    # The migration role's password never reaches the app.
    assert "keeplane-migration-db" not in app


@pytest.mark.parametrize("mode", ["managed", "existing"])
def test_cr_08_migration_job_reads_its_own_secret_at_each_run(chart, mode, tmp_path):
    output = render(chart, mode, tmp_path)
    job = workload(chart, output, "Job", "keeplane-accounts-migrate")
    assert "subPath" not in job
    assert chart.volumes(job)["database-credentials"] == ("secret", "keeplane-migration-db")
    assert chart.volumes(job)["database-ca"] == ("secret", "keeplane-database-ca")
    assert "keeplane-app-db" not in job
    assert "pre-install,pre-upgrade" in job


def test_cr_09_managed_gateway_loads_key_hashes_from_the_keys_secret(chart, tmp_path):
    output = render(chart, "managed", tmp_path)
    copies = workload(chart, output, "StatefulSet", "keeplane-gateway")
    container = chart.containers(copies)[0]
    hashes = {name: from_secret for name, _, from_secret in chart.env(container)
              if name in ("GATEWAY_RUNTIME_KEY_HASH", "GATEWAY_ADMIN_KEY_HASH")}
    assert hashes == {"GATEWAY_RUNTIME_KEY_HASH": True, "GATEWAY_ADMIN_KEY_HASH": True}
    assert "name: keeplane-gateway-keys" in container
    assert "subPath" not in copies
    # Read at start: the copies restart to load new hashes. Without the
    # rotation lines each policy holds only the current hash.
    assert "${GATEWAY_ADMIN_KEY_HASH}" in output and "${GATEWAY_RUNTIME_KEY_HASH}" in output
    assert "_KEY_HASH_NEXT" not in output
    policies = chart.key_policies("\n".join(chart.of_kind(output, "ConfigMap")))
    assert policies == {"ui": ("strict", ["${GATEWAY_ADMIN_KEY_HASH}"]),
                        "llm": ("strict", ["${GATEWAY_RUNTIME_KEY_HASH}"])}


NEXT_ENV = {
    "GATEWAY_RUNTIME_KEY_HASH_NEXT": "runtime-key-hash-next",
    "GATEWAY_ADMIN_KEY_HASH_NEXT": "admin-key-hash-next",
}


def next_entry(name, key, **reference):
    return {"name": name, "valueFrom": {"secretKeyRef": {
        "name": "keeplane-gateway-keys", "key": key, **reference}}}


def rotation_values(chart, extra_env=None, policies=("ui", "llm")):
    """The documented rotation lines added to the managed PostgreSQL values."""
    values = chart.postgres_values("managed")
    gateway = values["agentgateway-standalone"]
    entries = [next_entry(name, key) for name, key in NEXT_ENV.items()]
    gateway["extraEnv"] = gateway["extraEnv"] + (entries if extra_env is None else extra_env)
    variables = {"ui": "GATEWAY_ADMIN_KEY_HASH", "llm": "GATEWAY_RUNTIME_KEY_HASH"}
    for section in policies:
        variable = variables[section]
        gateway["config"].setdefault(section, {})["policies"] = {"apiKey": {"keys": [
            {"keyHash": "${" + variable + "}"}, {"keyHash": "${" + variable + "_NEXT}"},
        ]}}
    return values


def render_values(chart, values, tmp_path, label):
    path = tmp_path / (label + ".json")
    path.write_text(json.dumps(values))
    return chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                     "-f", str(path))


def test_cr_13_a_rotation_adds_the_next_key_hash_from_the_keys_secret(chart, tmp_path):
    result = render_values(chart, rotation_values(chart), tmp_path, "rotation")
    assert result.returncode == 0, result.stderr
    output = result.stdout
    copies = workload(chart, output, "StatefulSet", "keeplane-gateway")
    references = chart.gateway_env_refs(chart.containers(copies)[0])
    for name, key in NEXT_ENV.items():
        assert references[name] == ("keeplane-gateway-keys", key)
    assert "optional:" not in copies
    policies = chart.key_policies("\n".join(chart.of_kind(output, "ConfigMap")))
    assert policies == {
        "ui": ("strict", ["${GATEWAY_ADMIN_KEY_HASH}", "${GATEWAY_ADMIN_KEY_HASH_NEXT}"]),
        "llm": ("strict", ["${GATEWAY_RUNTIME_KEY_HASH}", "${GATEWAY_RUNTIME_KEY_HASH_NEXT}"]),
    }
    # No key or key hash is rendered; only the Secret is referenced.
    assert not re.search(r"(?<!@)sha256:[0-9a-f]{64}", output)
    assert not chart.of_kind(output, "Secret")
    # One policy can rotate on its own.
    admin_only = rotation_values(
        chart, [next_entry("GATEWAY_ADMIN_KEY_HASH_NEXT", "admin-key-hash-next")], ("ui",))
    assert render_values(chart, admin_only, tmp_path, "admin-only").returncode == 0


def test_cr_14_the_next_key_comes_only_from_the_keys_secret(chart, tmp_path):
    literal = {"name": "GATEWAY_ADMIN_KEY_HASH_NEXT", "value": "sha256:" + "e" * 64}
    runtime_next = next_entry("GATEWAY_RUNTIME_KEY_HASH_NEXT", "runtime-key-hash-next")
    refused = {
        "policy-without-env": rotation_values(chart, []),
        "env-without-policy": rotation_values(chart, None, ()),
        "optional-entry": rotation_values(chart, [runtime_next, next_entry(
            "GATEWAY_ADMIN_KEY_HASH_NEXT", "admin-key-hash-next", optional=True)]),
        "literal-hash": rotation_values(chart, [runtime_next, literal]),
        "other-secret": rotation_values(chart, [runtime_next, {
            "name": "GATEWAY_ADMIN_KEY_HASH_NEXT", "valueFrom": {"secretKeyRef": {
                "name": "other-keys", "key": "admin-key-hash-next"}}}]),
        "current-hash-as-next": rotation_values(chart, [runtime_next, next_entry(
            "GATEWAY_ADMIN_KEY_HASH_NEXT", "admin-key-hash")]),
        "repeated-entry": rotation_values(chart, [
            runtime_next, *[next_entry("GATEWAY_ADMIN_KEY_HASH_NEXT", "admin-key-hash-next")] * 2]),
    }
    swapped = rotation_values(chart)
    swapped["agentgateway-standalone"]["config"]["ui"]["policies"]["apiKey"]["keys"].reverse()
    refused["swapped-order"] = swapped
    third = rotation_values(chart)
    third["agentgateway-standalone"]["config"]["llm"]["policies"]["apiKey"]["keys"].append(
        {"keyHash": "sha256:" + "f" * 64})
    refused["literal-third-hash"] = third
    no_secret = rotation_values(chart)
    no_secret["gateway"]["keysSecret"] = ""
    refused["no-keys-secret"] = no_secret
    for label, values in refused.items():
        result = render_values(chart, values, tmp_path, label)
        assert result.returncode != 0, label
        assert "gateway.keysSecret" in result.stderr or "key policy" in result.stderr, label
        assert "sha256:" + "e" * 64 not in result.stderr
