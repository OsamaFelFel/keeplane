"""Credential rotation building blocks: password choice and gateway key checks.

Cases CR-U1 to CR-U8 in tests/integration/credential-rotation-cases.md.
"""

import hashlib
import logging
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from common import credential_check, web
from common.database_password import DatabasePasswordUnavailable, RotatingPassword
from integrations.gateway.adapter import AgentgatewayModelAdapter


class Refused(Exception):
    pass


AUTH_FAILED = (
    'connection failed: connection to server at "10.0.0.5", port 5432 failed: '
    'FATAL:  password authentication failed for user "keeplane_app"'
)
NETWORK_DOWN = (
    'connection failed: connection to server at "10.0.0.5", port 5432 failed: '
    "Connection refused\n\tIs the server running on that host and accepting TCP/IP connections?"
)


class Database:
    """A role with one password, as PostgreSQL has, that may be unreachable."""

    def __init__(self, password):
        self.password, self.attempts, self.reachable = password, [], True

    def open(self, password):
        self.attempts.append(password)
        if not self.reachable:
            raise Refused(NETWORK_DOWN)
        if password != self.password:
            raise Refused(AUTH_FAILED)
        return "connection"


def test_cr_u1_password_file_is_read_for_every_connection(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("first\n")
    rotating, database = RotatingPassword(secret), Database("first")
    assert rotating.connect(database.open, Refused) == "connection"
    database.password = "second"
    secret.write_text("second\n")
    assert rotating.connect(database.open, Refused) == "connection"
    # The new file was tried first and accepted; nothing else was needed.
    assert database.attempts == ["first", "second"]
    assert rotating.previous_in_use is False


def test_cr_u2_documented_order_never_refuses_a_request(tmp_path, caplog):
    secret = tmp_path / "password"
    secret.write_text("first")
    rotating, database = RotatingPassword(secret), Database("first")
    rotating.connect(database.open, Refused)
    secret.write_text("second")  # The Secret changes first.
    caplog.set_level(logging.WARNING)
    for _ in range(3):
        assert rotating.connect(database.open, Refused) == "connection"
    assert rotating.previous_in_use is True
    # One refused try per process, then the accepted password is tried first.
    assert database.attempts == ["first", "second", "first", "first", "first"]
    database.password = "second"  # Then the role's password changes.
    assert rotating.connect(database.open, Refused) == "connection"
    assert rotating.connect(database.open, Refused) == "connection"
    assert database.attempts[5:] == ["first", "second", "second"]
    assert rotating.previous_in_use is False
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert "still using the previous password" in messages[0]
    assert "accepted the password in the mounted file" in messages[1]
    assert not any("first" in text or "second" in text for text in messages)


def test_cr_u3_never_uses_a_password_the_database_has_not_accepted(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("wrong")
    rotating, database = RotatingPassword(secret), Database("right")
    with pytest.raises(Refused):
        rotating.connect(database.open, Refused)
    secret.write_text("")
    with pytest.raises(DatabasePasswordUnavailable):
        rotating.connect(database.open, Refused)
    secret.unlink()
    with pytest.raises(DatabasePasswordUnavailable):
        rotating.connect(database.open, Refused)
    assert database.attempts == ["wrong"]


def test_cr_u3b_unreadable_file_keeps_the_accepted_password(tmp_path):
    """A process that read its file and then dropped privileges keeps working."""
    secret = tmp_path / "password"
    secret.write_text("right")
    rotating, database = RotatingPassword(secret), Database("right")
    rotating.connect(database.open, Refused)
    secret.unlink()
    assert rotating.connect(database.open, Refused) == "connection"
    database.password = "changed"
    with pytest.raises(Refused):
        rotating.connect(database.open, Refused)
    assert database.attempts == ["right", "right", "right"]


def test_cr_u3c_an_unreachable_database_is_not_a_refused_password(tmp_path, caplog):
    secret = tmp_path / "password"
    secret.write_text("first")
    rotating, database = RotatingPassword(secret), Database("first")
    rotating.connect(database.open, Refused)
    secret.write_text("second")
    database.reachable = False
    caplog.set_level(logging.WARNING)
    with pytest.raises(Refused):
        rotating.connect(database.open, Refused)
    # The network error was raised at once: no other password was tried, the
    # process did not switch to "previous password" mode, nothing was logged.
    assert database.attempts == ["first", "second"]
    assert rotating.previous_in_use is False
    assert caplog.records == []


@pytest.mark.parametrize(
    ("message", "refused"),
    [
        (AUTH_FAILED, True),
        ('FATAL:  no pg_hba.conf entry for host "10.0.0.9", user "app"', True),
        ('FATAL:  role "app" is not permitted to log in', True),
        (NETWORK_DOWN, False),
        ("timeout expired", False),
        ("SSL error: certificate verify failed", False),
        ('could not translate host name "db" to address', False),
    ],
)
def test_cr_u3d_password_refusal_is_told_apart_from_unreachable(message, refused):
    from common.database_password import is_authentication_failure

    assert is_authentication_failure(Refused(message)) is refused


def test_cr_u4_gateway_key_refusal_is_reported_as_unavailable_not_signed_out(caplog):
    caplog.set_level(logging.WARNING)
    with patch.object(web.MODEL_GATEWAY, "request", return_value=(401, {"error": "x"})):
        status, body = web.gateway_runtime(log_refusal=True)
    assert status == 503
    assert body == {"error": credential_check.KEY_REFUSED}
    assert "restart the gateway copies" in body["error"]
    assert any("HTTP 401" in record.getMessage() for record in caplog.records)
    with patch.object(web.MODEL_GATEWAY, "request", return_value=(503, {"error": "down"})):
        assert web.gateway_runtime() == (503, {"error": "down"})


def test_cr_u5_gateway_health_fails_on_a_refused_key_without_logging(rf, caplog):
    caplog.set_level(logging.WARNING)
    with patch.object(web.MODEL_GATEWAY, "request", return_value=(403, {})):
        for _ in range(5):
            response = web.gateway_health(rf.get("/health"))
    assert response.status_code == 503
    # The public endpoint says only that the gateway is unavailable, and a
    # probe calling it repeatedly writes nothing to the log.
    assert response.content == b'{"gateway": "unavailable"}'
    assert caplog.records == []


def key_files(directory, keys):
    for name, value in keys.items():
        (directory / name).write_text(value)
    return {"runtime_key_file": str(directory / "runtime-key"),
            "admin_key_file": str(directory / "admin-key")}


def test_cr_u7_next_keys_are_checked_only_when_mounted(tmp_path):
    current = {"admin-key": "a" * 64, "runtime-key": "r" * 64}
    accepted = {*current.values(), "b" * 64}
    sent = []

    def answer(self, path, **_):
        key_file = self.admin_key_file if path.startswith("/api/") else self.runtime_key_file
        key = Path(key_file).read_text().strip()
        sent.append((self.base_url, path, key))
        return (200, {}) if key in accepted else (401, {})

    copy = AgentgatewayModelAdapter("http://copy-0", **key_files(tmp_path, current))
    with patch.object(AgentgatewayModelAdapter, "request", answer):
        assert credential_check.gateway_status([copy]) == [
            {"address": "http://copy-0", "admin_key": "accepted", "runtime_key": "accepted"}
        ]
        key_files(tmp_path, {"admin-key-next": "b" * 64, "runtime-key-next": "s" * 64})
        sent.clear()
        rows = credential_check.gateway_status([copy])
    # The admin next key is accepted and the runtime next key refused, each
    # sent on the path that needs it, to the copy's own address.
    assert rows == [{"address": "http://copy-0", "admin_key": "accepted",
                     "runtime_key": "accepted", "admin_key_next": "accepted",
                     "runtime_key_next": "refused"}]
    assert sorted(sent) == sorted([
        ("http://copy-0", "/api/runtime", "a" * 64),
        ("http://copy-0", "/v1/models", "r" * 64),
        ("http://copy-0", "/api/runtime", "b" * 64),
        ("http://copy-0", "/v1/models", "s" * 64),
    ])
    assert not any(key in repr(rows) for key in ("a" * 64, "b" * 64, "r" * 64, "s" * 64))


@pytest.mark.parametrize(("next_answer", "passed"), [
    (None, True), ("accepted", True), ("refused", False), ("unreadable", False),
])
def test_cr_u7_a_next_key_counts_only_when_mounted(next_answer, passed):
    row = {"address": "x", "admin_key": "accepted", "runtime_key": "accepted"}
    if next_answer:
        row["admin_key_next"] = next_answer
    with patch.object(credential_check, "database_status", return_value="connected"), \
            patch.object(credential_check, "gateway_models", return_value=[]), \
            patch.object(credential_check, "approvals", return_value=[]), \
            patch.object(credential_check, "gateway_status", return_value=[row]):
        assert credential_check.check(SimpleNamespace(base_url="x"), [])[1] is passed


ROOT = Path(__file__).resolve().parents[2]
KEY_GUIDES = ("docs/guide/kubernetes-installation-reference.md",
              "docs/guide/gateway-configuration.md")


def key_commands():
    """Each guide's shell block that makes keys, up to its first kubectl line."""
    found = []
    for guide in KEY_GUIDES:
        for block in re.findall(r"```sh\n(.*?)```", (ROOT / guide).read_text(), re.S):
            if "openssl rand" in block:
                lines = [line.strip() for line in block.splitlines()]
                end = next((n for n, line in enumerate(lines) if line.startswith("kubectl")),
                           len(lines))
                found.append((guide, "\n".join(lines[:end])))
    return found


def test_cr_u8_documented_key_commands_make_keys_keeplane_accepts(tmp_path):
    from model_registry.runtime_callback import private_key

    if not (shutil.which("openssl") and shutil.which("shasum")):
        pytest.skip("openssl and shasum are needed to run the documented commands")
    # No guide's command makes a base64 key, which can hold + / and =.
    for guide in sorted((ROOT / "docs").rglob("*.md")):
        for block in re.findall(r"```(?:sh|bash)\n(.*?)```", guide.read_text(), re.S):
            assert "rand -base64" not in block, guide
    commands = key_commands()
    assert [guide for guide, _ in commands] == list(KEY_GUIDES)
    for number, (guide, script) in enumerate(commands):
        directory = tmp_path / str(number)
        directory.mkdir()
        # A base64 key failed only some of the time, so make keys several times.
        for _ in range(8):
            subprocess.run(["sh", "-ec", script], cwd=directory, check=True)
            keys = sorted(p for p in directory.iterdir() if "-hash" not in p.name)
            assert [p.name.split("-key")[0] for p in keys] == ["admin", "runtime"], guide
            for key in keys:
                value = private_key(str(key))  # Keeplane's own key format check
                assert len(value) == 64 and value == key.read_bytes(), guide
                hashed = key.with_name(key.name.replace("-key", "-key-hash"))
                assert hashed.read_text() == "sha256:" + hashlib.sha256(value).hexdigest()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, {}, "accepted"),
        (401, {}, "refused"),
        (403, {}, "refused"),
        (503, {"error": "Gateway credential unavailable"}, "unreadable"),
        (503, {"error": "Gateway unavailable"}, "unreachable"),
        (500, {}, "unreachable"),
    ],
)
def test_cr_u6_key_check_names_each_outcome(status, body, expected):
    assert credential_check.key_status(status, body) == expected
