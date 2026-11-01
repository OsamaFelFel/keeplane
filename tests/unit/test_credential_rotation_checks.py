"""Credential rotation building blocks: password choice and gateway key checks.

Cases CR-U1 to CR-U6 in tests/integration/credential-rotation-cases.md.
"""

import logging
from unittest.mock import patch

import pytest
from common import credential_check, web
from common.database_password import DatabasePasswordUnavailable, RotatingPassword


class Refused(Exception):
    pass


class Database:
    """A role with one password, as PostgreSQL has."""

    def __init__(self, password):
        self.password, self.attempts = password, []

    def open(self, password):
        self.attempts.append(password)
        if password != self.password:
            raise Refused()
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


def test_cr_u4_gateway_key_refusal_is_reported_as_unavailable_not_signed_out(caplog):
    caplog.set_level(logging.WARNING)
    with patch.object(web.MODEL_GATEWAY, "request", return_value=(401, {"error": "x"})):
        status, body = web.gateway_runtime()
    assert status == 503
    assert body == {"error": credential_check.KEY_REFUSED}
    assert "restart the gateway copies" in body["error"]
    assert any("HTTP 401" in record.getMessage() for record in caplog.records)
    with patch.object(web.MODEL_GATEWAY, "request", return_value=(503, {"error": "down"})):
        assert web.gateway_runtime() == (503, {"error": "down"})


def test_cr_u5_gateway_health_fails_on_a_refused_key(rf):
    with patch.object(web.MODEL_GATEWAY, "request", return_value=(403, {})):
        response = web.gateway_health(rf.get("/health"))
    assert response.status_code == 503
    # The public endpoint says only that the gateway is unavailable.
    assert response.content == b'{"gateway": "unavailable"}'


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
