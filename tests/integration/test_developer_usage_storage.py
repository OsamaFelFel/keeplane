"""Developer usage through separate app processes on SQLite and PostgreSQL.

Spec 009 ST31 (D191, ADR 029). Cases DU-S1 to DU-S6 in developer-usage-cases.md.
PostgreSQL cases run when ``KEEPLANE_TEST_POSTGRES_*`` names a disposable
server (CI's PostgreSQL job sets them); elsewhere they are skipped.
"""

import json
import os
import secrets
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.integration import test_audit_persistence as persistence

PROCESS = persistence.ROOT / "tests/fixtures/usage_process.py"
database = persistence.database


class UsageProcess(persistence.AppProcess):
    """The Audit harness's line protocol, running the usage fixture instead."""

    def __init__(self, env):
        self.child = subprocess.Popen(
            [sys.executable, str(PROCESS)],
            cwd=persistence.ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


@pytest.fixture
def app(database, tmp_path):
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
        PYTHONPATH=os.pathsep.join(
            [str(persistence.ROOT / "components/control-plane"), str(persistence.ROOT)]
        ),
        PYTHONDONTWRITEBYTECODE="1",
        DJANGO_SETTINGS_MODULE="config.settings",
        DJANGO_SECRET_KEY_FILE=str(signing),
        FIRST_ADMIN_PASSWORD_FILE=str(password),
    )
    started = []

    def start():
        started.append(UsageProcess(env))
        return started[-1]

    first = start()
    first.ask("migrate")
    project = str(uuid.uuid4())
    accounts = first.ask("setup", project_id=project)
    yield SimpleNamespace(
        first=first,
        start=start,
        project=project,
        dev=accounts["usage-dev"],
        other=accounts["usage-other"],
    )
    for process in started:
        process.stop()


def report(app, **changes):
    body = {
        "project_id": app.project,
        "model": "coder",
        "input_tokens": 1000,
        "output_tokens": 250,
        "requests": 2,
        "requests_without_usage": 1,
    }
    body.update(changes)
    return body


def post(process, token, body):
    return process.ask("call", method="post", token=token, body=body)["status"]


def read(process, token, query="?tz=UTC"):
    return process.ask("call", method="get", token=token, query=query)


def test_du_s1_only_the_signed_in_developers_totals_come_back(app):
    assert post(app.first, app.dev["token"], report(app)) == 204
    assert post(app.first, app.other["token"], report(app, input_tokens=7)) == 204
    mine = read(app.first, app.dev["token"])["body"]["models"]
    assert mine == [
        {
            "model": "coder",
            "cost_status": "no_list_price",
            "today": {
                "input_tokens": 1000,
                "output_tokens": 250,
                "requests": 2,
                "requests_without_usage": 1,
                "estimated_cost": None,
                "cost_partial": False,
            },
            "this_month": {
                "input_tokens": 1000,
                "output_tokens": 250,
                "requests": 2,
                "requests_without_usage": 1,
                "estimated_cost": None,
                "cost_partial": False,
            },
        }
    ]
    assert (
        read(app.first, app.other["token"])["body"]["models"][0]["today"][
            "input_tokens"
        ]
        == 7
    )


def test_du_s2_an_account_id_in_the_report_is_ignored(app):
    body = report(app, account_id=app.other["id"], user_id=app.other["id"])
    assert post(app.first, app.dev["token"], body) == 204
    assert {row["user_id"] for row in app.first.ask("rows")} == {app.dev["id"]}


def test_du_s3_a_model_the_project_doesnt_allow_is_refused(app):
    assert post(app.first, app.dev["token"], report(app, model="outside")) == 403
    assert (
        post(app.first, app.dev["token"], report(app, project_id=str(uuid.uuid4())))
        == 403
    )
    assert app.first.ask("rows") == []


def test_du_s4_cookies_dont_authenticate(app):
    cookies = {"keeplane_session": app.dev["token"], "sessionid": app.dev["token"]}
    for method in ("get", "post"):
        answer = app.first.ask(
            "call", method=method, cookies=cookies, body=report(app), query="?tz=UTC"
        )
        assert answer["status"] == 401
    assert app.first.ask("rows") == []


def test_du_s5_no_prompt_or_path_is_stored(app):
    secret = "storage-secret-prompt-text"
    body = report(app, prompt=secret, path="/srv/" + secret, answer=secret)
    assert post(app.first, app.dev["token"], body) == 204
    stored = app.first.ask("rows")
    assert len(stored) == 1 and secret not in str(stored)
    assert set(stored[0]) == {
        "id",
        "user_id",
        "model_id",
        "hour",
        "input_tokens",
        "output_tokens",
        "requests",
        "requests_without_usage",
    }


def test_du_s6_two_app_copies_add_to_one_hourly_total_and_old_totals_go(app):
    second = app.start()
    now = datetime.now(timezone.utc)
    old = (now.replace(day=1) - timedelta(days=40)).replace(hour=0).isoformat()
    app.first.ask("old_total", user_id=app.other["id"], hour=old)
    one = report(
        app, input_tokens=10, output_tokens=1, requests=1, requests_without_usage=0
    )
    # Both copies get their commands before either answers, so they write at once.
    command = json.dumps(
        {
            "action": "repeat",
            "method": "post",
            "token": app.dev["token"],
            "body": one,
            "count": 20,
        }
    )
    for process in (app.first, second):
        process.child.stdin.write(command + "\n")
        process.child.stdin.flush()
    for process in (app.first, second):
        answer = json.loads(process.child.stdout.readline())
        assert answer == {"ok": True, "result": [204] * 20}, answer
    stored = second.ask("rows")
    # The total from before the previous month was deleted by the first report.
    assert app.other["id"] not in {row["user_id"] for row in stored}
    # Forty reports in at most two hours (the test may cross an hour boundary).
    assert sum(row["requests"] for row in stored) == 40
    assert sum(row["input_tokens"] for row in stored) == 400
    assert len(stored) <= 2 and {row["user_id"] for row in stored} == {app.dev["id"]}
