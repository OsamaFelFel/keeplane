"""Audit search, kind filter and paging on persisted records across processes."""

import json
import os
import secrets
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROCESS = ROOT / "tests/fixtures/audit_process.py"
BREAK_GLASS = "break_glass_sign_ins"
POSTGRES_ENV = "KEEPLANE_TEST_POSTGRES_HOST"


class AppProcess:
    """A separate control-plane process with its own database connection."""

    def __init__(self, env):
        self.child = subprocess.Popen(
            [sys.executable, str(PROCESS)],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def ask(self, action, **values):
        self.child.stdin.write(json.dumps({"action": action, **values}) + "\n")
        self.child.stdin.flush()
        line = self.child.stdout.readline()
        if not line:
            self.child.wait(timeout=30)
            pytest.fail("App process stopped: " + self.child.stderr.read()[-2000:])
        answer = json.loads(line)
        assert answer["ok"], answer.get("error")
        return answer["result"]

    def records(self, **query):
        return self.ask("records", query=query)

    def stop(self):
        if self.child.poll() is None:
            self.child.stdin.close()
            try:
                self.child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=30)
        self.child.stdout.close()
        self.child.stderr.close()


@contextmanager
def postgres_database():
    psycopg = pytest.importorskip("psycopg")
    name = "keeplane_audit_" + uuid.uuid4().hex[:12]
    target = {
        "host": os.environ[POSTGRES_ENV],
        "port": os.environ.get("KEEPLANE_TEST_POSTGRES_PORT", "5432"),
        "user": os.environ["KEEPLANE_TEST_POSTGRES_USER"],
        "password": Path(os.environ["KEEPLANE_TEST_POSTGRES_PASSWORD_FILE"])
        .read_text()
        .strip(),
        "dbname": os.environ.get("KEEPLANE_TEST_POSTGRES_NAME", "postgres"),
        "sslmode": os.environ.get("KEEPLANE_TEST_POSTGRES_SSLMODE", "disable"),
    }
    with psycopg.connect(**target, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield {
            "KEEPLANE_DATABASE_HOST": target["host"],
            "KEEPLANE_DATABASE_PORT": target["port"],
            "KEEPLANE_DATABASE_NAME": name,
            "KEEPLANE_DATABASE_USER": target["user"],
            "KEEPLANE_DATABASE_PASSWORD_FILE": os.environ[
                "KEEPLANE_TEST_POSTGRES_PASSWORD_FILE"
            ],
            "KEEPLANE_DATABASE_SSLMODE": target["sslmode"],
        }
    finally:
        with psycopg.connect(**target, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path):
    if request.param == "sqlite":
        yield {"KEEPLANE_SQLITE_PATH": str(tmp_path / "keeplane.sqlite3")}
        return
    if not os.environ.get(POSTGRES_ENV):
        pytest.skip("Set KEEPLANE_TEST_POSTGRES_* to a disposable PostgreSQL server")
    with postgres_database() as values:
        yield values


@pytest.fixture
def start_process(database, tmp_path):
    signing = tmp_path / "signing"
    signing.write_text(secrets.token_urlsafe(48))
    password = tmp_path / "first-admin-password"
    password.write_text(secrets.token_urlsafe(24) + "\n")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("KEEPLANE_", "DJANGO_"))
    }
    env.update(
        database,
        PYTHONPATH=os.pathsep.join([str(ROOT / "components/control-plane"), str(ROOT)]),
        PYTHONDONTWRITEBYTECODE="1",
        DJANGO_SETTINGS_MODULE="config.settings",
        DJANGO_SECRET_KEY_FILE=str(signing),
        FIRST_ADMIN_PASSWORD_FILE=str(password),
    )
    started = []

    def start():
        process = AppProcess(env)
        started.append(process)
        return process

    yield start
    for process in started:
        process.stop()


def all_pages(process, **query):
    rows, page = [], 1
    while True:
        result = process.records(page=page, page_size=10, **query)
        rows += result["records"]
        if not result["has_more"]:
            assert len(rows) == result["total"]
            return rows
        page += 1


def finding_checks(process):
    """What an admin sees for each search, kind and page on a shared database."""
    everything = process.records(page=1, page_size=25)
    second = process.records(page=2, page_size=25)
    return {
        "first_page": [row["id"] for row in everything["records"]],
        "second_page": [row["id"] for row in second["records"]],
        "total": everything["total"],
        "has_more": [everything["has_more"], second["has_more"]],
        "all_ids": [row["id"] for row in all_pages(process)],
        "break_glass": all_pages(process, kind=BREAK_GLASS),
        "break_glass_by_name": process.records(kind=BREAK_GLASS, search="FIRST-ADMIN")[
            "total"
        ],
        "searched": [row["what"] for row in all_pages(process, search="rule 2")],
        "settings_searching_sign_ins": process.records(
            kind="settings", search="Break-glass"
        )["total"],
        "past_last_page": process.records(page=9, page_size=25)["records"],
    }


def test_as_01_02_two_processes_and_a_restart_find_the_same_records(start_process):
    writer, reader = start_process(), start_process()
    writer.ask("migrate")
    writer.ask("settings", count=30, prefix="Routing rule", who="routing-admin")
    reader.ask("sign_in", count=3)

    seen = finding_checks(writer)
    assert seen == finding_checks(reader)
    assert seen["total"] == 33 and len(seen["first_page"]) == 25
    assert len(seen["second_page"]) == 8 and seen["has_more"] == [True, False]
    assert seen["first_page"] + seen["second_page"] == seen["all_ids"]
    assert seen["all_ids"] == sorted(set(seen["all_ids"]), reverse=True)
    assert [row["kind"] for row in seen["break_glass"]] == [BREAK_GLASS] * 3
    assert {row["who"] for row in seen["break_glass"]} == {"first-admin"}
    assert seen["break_glass_by_name"] == 3
    assert seen["searched"] == [f"Routing rule {n}" for n in range(29, 19, -1)]
    assert seen["settings_searching_sign_ins"] == 0
    assert seen["past_last_page"] == []

    writer.stop()
    reader.stop()
    assert finding_checks(start_process()) == seen


def test_as_03_records_from_the_previous_schema_survive_upgrade(start_process):
    app = start_process()
    app.ask("migrate", target=[["accounts", "0001_initial"]])
    app.ask("previous_records", count=27)
    app.ask("migrate")
    app.stop()

    upgraded = start_process()
    upgraded.ask("sign_in", count=1)
    newest = upgraded.records(page=1, page_size=25)
    assert newest["total"] == 29 and newest["has_more"]
    assert newest["records"][0]["kind"] == BREAK_GLASS
    sign_ins = all_pages(upgraded, kind=BREAK_GLASS)
    assert len(sign_ins) == 2 and sign_ins[0]["id"] > sign_ins[1]["id"]
    legacy = all_pages(upgraded, search="legacy routing")
    assert len(legacy) == 27
    assert legacy[0]["what"] == "Legacy routing change 26"
    assert all(row["when"].endswith("+00:00") for row in legacy)
    assert upgraded.records(kind="settings", search="legacy-admin")["total"] == 27


def test_as_04_the_audit_api_finds_records_for_an_admin_only(start_process, tmp_path):
    app, other = start_process(), start_process()
    app.ask("migrate")
    password = (tmp_path / "first-admin-password").read_text().strip()

    def call(process, path, session=None):
        return process.ask("http", method="GET", path=path, session=session)

    def sign_in(process, username, secret):
        answer = process.ask(
            "http",
            method="POST",
            path="/api/session",
            body={"username": username, "password": secret},
        )
        assert answer["status"] == 200
        return answer["session"]

    admin = sign_in(app, "first-admin", password)
    app.ask("settings", count=30, prefix="Routing rule", who="routing-admin")
    sign_in(other, "first-admin", password)

    def found(path):
        answer = call(other, path, admin)
        assert answer["status"] == 200, answer
        return answer["body"]

    first, second = found("/api/audit/records"), found("/api/audit/records?page=2")
    assert first["total"] == 32 and len(first["records"]) == 25 and first["has_more"]
    assert len(second["records"]) == 7 and not second["has_more"]
    ids = [row["id"] for row in first["records"] + second["records"]]
    assert ids == sorted(set(ids), reverse=True)
    shown = found(f"/api/audit/records?kind={BREAK_GLASS}")
    assert shown["total"] == 2
    assert {row["kind"] for row in shown["records"]} == {BREAK_GLASS}
    settings = found("/api/audit/records?kind=settings&page=2")
    assert settings["total"] == 30 and len(settings["records"]) == 5
    assert {row["kind"] for row in settings["records"]} == {"settings"}
    searched = found("/api/audit/records?search=RULE%202")
    assert [row["what"] for row in searched["records"]] == [
        f"Routing rule {n}" for n in range(29, 19, -1)
    ]
    assert found("/api/audit/records?kind=settings&search=first-admin")["total"] == 0
    assert found(f"/api/audit/records?kind={BREAK_GLASS}&search=rule")["total"] == 0
    assert found("/api/audit/records?kind=model_answers")["total"] == 0
    assert found("/api/audit/records?page=3")["records"] == []

    for bad in ("kind=everything", "page=two", "page=0", "search=" + "x" * 81):
        assert call(other, "/api/audit/records?" + bad, admin)["status"] == 400
    assert call(other, "/api/audit/records")["status"] == 401
    created = app.ask(
        "http",
        method="POST",
        path="/api/users",
        session=admin,
        body={
            "username": "dev-reader",
            "password": "dev-reader-password",
            "role": "developer",
        },
    )
    assert created["status"] == 201
    developer = sign_in(other, "dev-reader", "dev-reader-password")
    refused = call(other, "/api/audit/records", developer)
    assert refused["status"] == 403 and "records" not in (refused["body"] or {})
