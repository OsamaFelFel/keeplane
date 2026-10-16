"""Actual controlled HTTP transport; the separate join uses the real issuer."""

import json

import pytest

from components.cli import device_login, keeplane
from components.cli.credential_profile import Profile, ProfileError, opened
from components.cli.server_connection import ConnectionError
from tests.unit.test_cli_browser_login import issuer  # noqa: F401


@pytest.fixture
def clock(monkeypatch):
    elapsed, waits = [0], []

    def sleep(seconds):
        waits.append(seconds)
        elapsed[0] += seconds

    monkeypatch.setattr(device_login, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(device_login, "sleep", sleep)
    return waits


def test_actual_device_command_profile_cadence_and_no_raw_credentials(
    issuer,  # noqa: F811 - imported pytest fixture
    clock,
    tmp_path,
    monkeypatch,
    capsys,
):
    issuer.device_errors = [
        {"error": "authorization_pending"},
        {"error": "slow_down"},
        {"error": "authorization_pending"},
    ]
    path = tmp_path / "profile"
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr(
        "sys.argv",
        [
            "keeplane",
            "login",
            "--device",
            "--server",
            issuer.url,
            "--profile",
            str(path),
        ],
    )
    assert keeplane.main() == 0
    assert clock == [5, 5, 10, 10]
    with opened(path) as store:
        credential = store.load()
    assert credential.actor_id == issuer.actor and credential.issuer == issuer.url
    output = capsys.readouterr()
    assert (
        issuer.user_code in output.out
        and issuer.url + "/oauth/confirm-device/" in output.out
    )
    assert all(
        secret not in output.out + output.err
        for secret in (issuer.device_code, issuer.access, issuer.refresh)
    )
    assert all(
        issuer.device_code.encode() not in file.read_bytes() for file in path.iterdir()
    )
    assert issuer.device_headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert all(
        "Cookie" not in headers and "Authorization" not in headers
        for _, headers in issuer.device_polls
    )
    with pytest.raises(ProfileError, match="signed in"):
        device_login.login(issuer.url, path)
    assert issuer.device_starts == 1


@pytest.mark.parametrize(
    "change", ["foreign", "code", "interval", "expiry", "duplicate", "large"]
)
def test_invalid_device_response_never_polls_or_saves(issuer, clock, tmp_path, change):  # noqa: F811
    body = {
        "verification_uri": issuer.url + "/oauth/confirm-device/",
        "user_code": issuer.user_code,
        "device_code": issuer.device_code,
        "interval": 5,
        "expires_in": 1800,
    }
    if change == "foreign":
        body["verification_uri"] = "https://foreign.invalid/oauth/confirm-device/"
    elif change == "code":
        body["device_code"] = "not a credential"
    elif change == "interval":
        body["interval"] = 0
    elif change == "expiry":
        body["expires_in"] = True
    elif change == "duplicate":
        body = (json.dumps(body)[:-1] + ',"interval":1}').encode()
    else:
        body["future"] = "x" * 4096
    issuer.device_body = body
    path = tmp_path / "profile"
    with pytest.raises(ConnectionError):
        device_login.login(issuer.url, path)
    assert not issuer.device_polls and not (path / "credential.json").exists()


def test_device_expiry_and_refusal_stop_without_persisting_source(
    issuer,  # noqa: F811 - imported pytest fixture
    clock,
    tmp_path,
):
    issuer.device_errors = [{"error": "authorization_pending"}]
    path = tmp_path / "timeout"
    with pytest.raises(ConnectionError, match="timed out"):
        device_login.login(issuer.url, path, timeout=9)
    assert clock == [5] and not (path / "credential.json").exists()
    issuer.device_errors = [
        {"error": "access_denied", "description": issuer.device_code}
    ]
    with pytest.raises(ConnectionError, match="refused") as error:
        device_login.login(issuer.url, tmp_path / "denied")
    assert issuer.device_code not in str(error.value)


def test_device_cancel_does_not_poll_and_post_exchange_failure_revokes(
    issuer,  # noqa: F811 - imported pytest fixture
    clock,
    tmp_path,
    monkeypatch,
):
    def cancel(_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        device_login.login(issuer.url, tmp_path / "cancel", announce=cancel)
    assert not issuer.device_polls

    def fail(*_):
        raise OSError("synthetic profile failure")

    monkeypatch.setattr(Profile, "save", fail)
    with pytest.raises(ProfileError):
        device_login.login(issuer.url, tmp_path / "failed-save")
    assert issuer.revocations == 1


def test_duplicate_pending_error_does_not_extend_wait(issuer, clock, tmp_path):  # noqa: F811
    issuer.device_errors = [
        b'{"error":"access_denied","error":"authorization_pending"}'
    ]
    with pytest.raises(ConnectionError, match="refused"):
        device_login.login(issuer.url, tmp_path / "duplicate")
    assert clock == [5]
