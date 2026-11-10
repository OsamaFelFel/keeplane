"""Task 003-03: sessions, CSRF and sign-in limits across two app copies.

Two separate control-plane processes share one database and one signing
secret, as two replicas behind one address do. A browser's cookies stay with
the test and go to either copy. Every case runs on a temporary SQLite file and,
when configured, on PostgreSQL. The plain-English cases are in
identity-replicas-cases.md.
"""

import json
import os
import secrets
import subprocess
import sys
import time

import pytest

from tests.integration import test_audit_persistence as persistence

ROOT = persistence.ROOT
PROCESS = ROOT / "tests/fixtures/identity_process.py"
ORIGIN = "http://127.0.0.1:3000"
ATTEMPTS = 5
WINDOW = 60
UNSAFE = ("POST", "PUT", "PATCH", "DELETE")
# Routes that take only an explicit bearer credential and never a browser
# cookie, so CSRF does not apply to them. A new one must be added here on
# purpose, after checking that it ignores the session cookie.
BEARER_ONLY = {
    "/api/runtime/usage",
    "/internal/runtime/provider-token",
    "/internal/runtime/installed-provider-token",
    "/internal/runtime/authorize",
    "/internal/runtime/authorize/selected",
    "/internal/runtime/installed/entry",
    "/internal/runtime/installed/selected",
    "/internal/runtime/installed/operator-validation",
    "/api/runtime/projects",
    "/api/runtime/session",
    "/api/runtime/provider-keys",
    "/api/runtime/projects/unknown/provider-keys",
    "/api/runtime/provider-keys/check",
    "/api/runtime/projects/unknown/model-choice",
    "/api/runtime/projects/unknown/model-alternatives",
    "/api/runtime/projects/unknown/task-model",
}

database = persistence.database


class AppCopy(persistence.AppProcess):
    """One app copy: a separate process with its own database connections."""

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

    def send(self, action, **values):
        self.child.stdin.write(json.dumps({"action": action, **values}) + "\n")
        self.child.stdin.flush()

    def receive(self):
        line = self.child.stdout.readline()
        if not line:
            self.child.wait(timeout=30)
            pytest.fail("App copy stopped: " + self.child.stderr.read()[-2000:])
        answer = json.loads(line)
        assert answer["ok"], answer.get("error")
        return answer["result"]

    def ask(self, action, **values):
        self.send(action, **values)
        return self.receive()


class Browser:
    """One browser's cookie jar, sent to whichever copy answers."""

    def __init__(self):
        self.cookies = {}

    def call(self, app, method, path, body=None, token=True, headers=None):
        sent = {"Origin": ORIGIN, "X-Keeplane-Action": "1", **(headers or {})}
        if token and method != "GET":
            sent.setdefault("X-CSRFToken", self.token)
        answer = app.ask(
            "http",
            method=method,
            path=path,
            body=body or {},
            cookies=self.cookies,
            headers=sent,
        )
        for name, value in answer["cookies"].items():
            if value:
                self.cookies[name] = value
            else:
                self.cookies.pop(name, None)
        return answer

    def open(self, app):
        """Load the sign-in page's options, which hands out the CSRF token."""
        answer = self.call(app, "GET", "/api/auth-options")
        assert answer["status"] == 200 and "csrftoken" in self.cookies
        self.token = answer["body"]["csrf_token"]
        return self

    def sign_in(self, app, username, password):
        answer = self.call(
            app, "POST", "/api/session", {"username": username, "password": password}
        )
        if answer["status"] == 200:
            # Signing in rotates the CSRF cookie; the page loads a new token.
            self.open(app)
        return answer


@pytest.fixture
def copies(database, tmp_path):
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
        PUBLIC_ORIGIN=ORIGIN,
    )
    first, second = AppCopy(env), AppCopy(env)
    first.ask("migrate")
    yield first, second, password.read_text().strip()
    for app in (first, second):
        app.stop()


def identity(browser, app):
    return browser.call(app, "GET", "/api/identity")


def test_idr_01_a_session_from_one_copy_works_and_ends_on_both(copies):
    first, second, password = copies
    browser = Browser().open(first)
    assert browser.sign_in(first, "first-admin", password)["status"] == 200
    seen = [identity(browser, app) for app in (first, second)]
    assert [answer["status"] for answer in seen] == [200, 200]
    assert seen[0]["body"] == seen[1]["body"]
    assert seen[1]["body"]["role"] == "admin"
    users = browser.call(second, "GET", "/api/users?search=first-admin")
    assert users["status"] == 200 and users["body"]["total"] == 1

    session = browser.cookies["keeplane_session"]
    out = browser.call(second, "POST", "/sign-out")
    assert out["status"] == 200 and "keeplane_session" not in browser.cookies
    # The same cookie, replayed to either copy, no longer signs anyone in.
    for app in (first, second):
        replay = app.ask(
            "http",
            method="GET",
            path="/api/identity",
            cookies={"keeplane_session": session},
            headers={},
        )
        assert replay["status"] == 401
    assert first.ask("stored")["sessions"] == 0


def test_idr_02_role_changes_on_one_copy_apply_at_once_on_the_other(copies):
    first, second, password = copies
    admin = Browser().open(first)
    admin.sign_in(first, "first-admin", password)
    created = admin.call(
        first,
        "POST",
        "/api/users",
        {"username": "dev-one", "password": "dev-one-password-1", "role": "developer"},
    )
    assert created["status"] == 201, created
    user_id = created["body"]["id"]

    developer = Browser().open(second)
    assert developer.sign_in(second, "dev-one", "dev-one-password-1")["status"] == 200
    assert developer.call(first, "GET", "/api/users")["status"] == 403

    promoted = admin.call(first, "PUT", f"/api/users/{user_id}/role", {"role": "admin"})
    assert promoted["status"] == 200, promoted
    # The developer's existing session gains admin access on both copies.
    for app in (second, first):
        assert developer.call(app, "GET", "/api/users")["status"] == 200

    demoted = admin.call(
        second, "PUT", f"/api/users/{user_id}/role", {"role": "developer"}
    )
    assert demoted["status"] == 200, demoted
    # Demotion ends the session everywhere, not only on the copy that made it.
    for app in (first, second):
        assert identity(developer, app)["status"] == 401
    assert identity(admin, first)["status"] == 200


def test_idr_03_csrf_tokens_are_shared_and_checked_by_both_copies(copies):
    first, second, password = copies
    browser = Browser().open(first)
    before_sign_in = browser.token

    # A token issued by one copy signs in through the other.
    assert browser.sign_in(second, "first-admin", password)["status"] == 200
    note = browser.call(first, "GET", "/api/edition-note")
    assert note["status"] == 200
    original = note["body"]["enabled"]

    # Signing in rotated the CSRF cookie, so the earlier token fails on both.
    for app in (first, second):
        stale = browser.call(
            app,
            "PUT",
            "/api/edition-note",
            {"enabled": not original},
            headers={"X-CSRFToken": before_sign_in},
        )
        assert (stale["status"], stale["body"]["code"]) == (403, "csrf_failed")

    # Another browser's token, or none, fails too.
    other = Browser().open(second)
    for headers, token in (({"X-CSRFToken": other.token}, True), ({}, False)):
        refused = browser.call(
            second,
            "PUT",
            "/api/edition-note",
            {"enabled": not original},
            token=token,
            headers=headers,
        )
        assert (refused["status"], refused["body"]["code"]) == (403, "csrf_failed")
    assert (
        browser.call(second, "GET", "/api/edition-note")["body"]["enabled"] == original
    )

    # The current token works on either copy, and each sees the other's change.
    changed = browser.call(first, "PUT", "/api/edition-note", {"enabled": not original})
    assert changed["status"] == 200
    assert browser.call(second, "GET", "/api/edition-note")["body"]["enabled"] is (
        not original
    )
    restored = browser.call(second, "PUT", "/api/edition-note", {"enabled": original})
    assert restored["status"] == 200
    assert (
        browser.call(first, "GET", "/api/edition-note")["body"]["enabled"] == original
    )


def test_idr_04_every_state_changing_route_refuses_a_request_without_a_token(copies):
    first, second, password = copies
    browser = Browser().open(first)
    browser.sign_in(first, "first-admin", password)
    found = first.ask("routes")["routes"]
    assert found == second.ask("routes")["routes"]
    paths = {route["path"] for route in found}
    bearer_only = {route["path"] for route in found if route["bearer_only"]}
    # The exempt routes are exactly the reviewed bearer-only list.
    assert bearer_only == BEARER_ONLY
    # Every account route the browser uses is in the table under test.
    assert {
        "/api/session",
        "/api/users",
        "/api/users/unknown",
        "/api/users/unknown/role",
        "/api/edition-note",
        "/api/edition-note/consume",
        "/sign-out",
        "/oauth/confirm-device/",
    } <= paths

    before = first.ask("snapshot")
    refused = 0
    for route in found:
        for app in (first, second):
            for method in UNSAFE:
                answer = browser.call(app, method, route["path"], token=False)
                where = (route["path"], method)
                if route["bearer_only"]:
                    # No CSRF check, but the session cookie opens nothing: these
                    # need their own credential, and fail closed (503) where
                    # that credential isn't configured.
                    assert answer["status"] in (401, 403, 405, 503), where
                    assert (answer["body"] or {}).get("code") != "csrf_failed", where
                else:
                    assert answer["status"] == 403, where
                    assert answer["body"]["code"] == "csrf_failed", where
                    refused += 1
    assert refused == (len(found) - len(bearer_only)) * 2 * len(UNSAFE)
    after = first.ask("snapshot")
    assert after == before
    # The session survived every refused sign-out.
    assert identity(browser, second)["status"] == 200


def wrong(username="first-admin"):
    return {"username": username, "password": "wrong-password-123"}


def test_idr_05_both_copies_share_one_sign_in_budget(copies):
    first, second, password = copies
    browser = Browser().open(first)
    statuses = [
        browser.call(app, "POST", "/api/session", wrong(name))["status"]
        for app, name in (
            (first, "first-admin"),
            (second, "FIRST-ADMIN"),
            (first, "First-Admin"),
            (second, "first-admin"),
            (second, "FIRST-admin"),
        )
    ]
    assert statuses == [401] * ATTEMPTS
    # Now even the right password is refused on both copies, with no session.
    for app in (first, second):
        answer = browser.sign_in(app, "first-admin", password)
        assert answer["status"] == 429
        assert 1 <= int(answer["retry_after"]) <= WINDOW
        assert "keeplane_session" not in browser.cookies
    assert first.ask("stored") == {
        "sessions": 0,
        "break_glass_records": 0,
        "budgets": [ATTEMPTS],
    }

    # An unknown account gets the same budget and answer, also across copies.
    unknown = [
        browser.call(app, "POST", "/api/session", wrong("nobody-here"))
        for app in (first, second) * 3
    ]
    assert [answer["status"] for answer in unknown] == [401] * ATTEMPTS + [429]
    assert unknown[-1]["body"] == answer["body"]


def test_idr_06_a_success_on_one_copy_clears_the_budget_on_the_other(copies):
    first, second, password = copies
    browser = Browser().open(first)
    for _ in range(ATTEMPTS - 1):
        assert browser.call(first, "POST", "/api/session", wrong())["status"] == 401
    assert browser.sign_in(second, "First-Admin", password)["status"] == 200
    assert first.ask("stored")["budgets"] == []
    for _ in range(ATTEMPTS):
        assert browser.call(first, "POST", "/api/session", wrong())["status"] == 401
    assert browser.call(second, "POST", "/api/session", wrong())["status"] == 429


def test_idr_07_simultaneous_attempts_on_both_copies_share_the_budget(copies):
    first, second, _ = copies
    browser = Browser().open(first)
    names = ("first-admin", "FIRST-ADMIN", "First-Admin", "first-ADMIN", "FIRST-admin")
    start_at = time.time() + 2
    for app in (first, second):
        app.send(
            "burst",
            attempts=[wrong(name) for name in names],
            start_at=start_at,
            cookies=browser.cookies,
            headers={
                "Origin": ORIGIN,
                "X-Keeplane-Action": "1",
                "X-CSRFToken": browser.token,
            },
        )
    statuses = first.receive()["statuses"] + second.receive()["statuses"]
    # Ten at once across both copies: five reach the password check.
    assert sorted(statuses) == [401] * ATTEMPTS + [429] * ATTEMPTS
    assert first.ask("stored") == {
        "sessions": 0,
        "break_glass_records": 0,
        "budgets": [ATTEMPTS],
    }
