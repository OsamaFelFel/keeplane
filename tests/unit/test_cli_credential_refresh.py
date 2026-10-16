"""Explicit refresh over actual synthetic HTTP, including ambiguous rotation."""

import json
import os
import stat
import uuid

import pytest

from components.cli import credential_refresh, keeplane
from components.cli.credential_profile import Credential, Profile, ProfileError, opened
from components.cli.server_connection import ConnectionError
from tests.unit import test_cli_browser_login as browser_cases

issuer = browser_cases.issuer


def saved(issuer, tmp_path, client="keeplane-cli", *, legacy=False):
    path = tmp_path / "profile"
    old = Credential(
        issuer.url, issuer.actor, "kpc_" + "o" * 43, "old_" + "r" * 43, client
    )
    with opened(path, create=True) as profile:
        profile.save(old)
    if legacy:
        data = json.loads((path / "credential.json").read_text())
        data["format"] = "keeplane-credential-v1"
        del data["client_id"]
        (path / "credential.json").write_text(json.dumps(data))
    issuer.expected_refresh, issuer.refresh_client = old.refresh_token, client
    return path, old


@pytest.mark.parametrize(
    "client,legacy",
    [
        ("keeplane-cli", False),
        ("keeplane-cli", True),
        ("keeplane-cli-device", False),
    ],
)
def test_actual_command_rotates_correct_client_once_and_admits_same_actor(
    issuer,
    tmp_path,
    monkeypatch,
    capsys,
    client,
    legacy,
):
    path, old = saved(issuer, tmp_path, client, legacy=legacy)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr("sys.argv", ["keeplane", "refresh", "--profile", str(path)])
    assert keeplane.main() == 0
    with opened(path) as profile:
        new = profile.load()
    assert (new.client_id, new.actor_id, new.issuer) == (
        client,
        old.actor_id,
        old.issuer,
    )
    assert (new.access_token, new.refresh_token) == (issuer.access, issuer.refresh)
    assert (
        json.loads((path / "credential.json").read_text())["format"]
        == "keeplane-credential-v2"
    )
    assert len(issuer.refresh_requests) == 1
    form, headers = issuer.refresh_requests[0]
    assert form == {
        "grant_type": "refresh_token",
        "client_id": client,
        "refresh_token": old.refresh_token,
    }
    assert "Cookie" not in headers and "Authorization" not in headers
    output = capsys.readouterr()
    assert all(
        secret not in output.out + output.err
        for secret in (
            old.access_token,
            old.refresh_token,
            new.access_token,
            new.refresh_token,
        )
    )
    assert "must_not_be_saved" not in (path / "credential.json").read_text()


@pytest.mark.parametrize("failure", ["actor", "account", "save", "cancel", "unchanged"])
def test_new_pair_is_withdrawn_and_old_profile_retained_on_admission_failure(
    issuer,
    tmp_path,
    monkeypatch,
    failure,
):
    path, old = saved(issuer, tmp_path)
    if failure == "actor":
        issuer.actor = str(uuid.uuid4())
    elif failure == "account":
        issuer.account_status = 503
    elif failure in {"save", "cancel"}:

        def fail(*_):
            raise (
                KeyboardInterrupt if failure == "cancel" else OSError("private details")
            )

        monkeypatch.setattr(Profile, "save", fail)
    else:
        issuer.access = old.access_token
    with pytest.raises((ProfileError, ConnectionError, KeyboardInterrupt)):
        credential_refresh.refresh(path)
    assert issuer.revocations == 1 and len(issuer.refresh_requests) == 1
    with opened(path) as profile:
        assert profile.load() == old


@pytest.mark.parametrize("status", [400, 503])
def test_exchange_failure_retains_state_without_retry(issuer, tmp_path, status):
    path, old = saved(issuer, tmp_path)
    issuer.token_status = status
    with pytest.raises(ConnectionError, match="server may have rotated"):
        credential_refresh.refresh(path)
    assert len(issuer.refresh_requests) == 1 and issuer.revocations == 0
    with opened(path) as profile:
        assert profile.load() == old


@pytest.mark.parametrize("status", [401, 503])
def test_cleanup_confirmation_is_distinguished(issuer, tmp_path, status):
    path, _ = saved(issuer, tmp_path)
    issuer.actor, issuer.revoke_status = str(uuid.uuid4()), status
    message = (
        "account changed" if status == 401 else "revocation could not be confirmed"
    )
    with pytest.raises((ProfileError, ConnectionError), match=message):
        credential_refresh.refresh(path)
    assert issuer.revocations == 1


def test_directory_sync_failure_revokes_the_already_replaced_pair(
    issuer,
    tmp_path,
    monkeypatch,
):
    path, _ = saved(issuer, tmp_path)
    original = os.fsync

    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("private directory details")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(ProfileError):
        credential_refresh.refresh(path)
    assert issuer.revocations == 1
    with opened(path) as profile:
        assert profile.load().access_token == issuer.access


@pytest.mark.parametrize(
    "change", ["unknown_client", "missing_client", "v1_extra", "duplicate"]
)
def test_strict_profile_version_and_client_metadata_refuse_before_exchange(
    issuer,
    tmp_path,
    change,
):
    path, _ = saved(issuer, tmp_path)
    target = path / "credential.json"
    data = json.loads(target.read_text())
    if change == "unknown_client":
        data["client_id"] = "foreign-client"
    elif change == "missing_client":
        del data["client_id"]
    elif change == "v1_extra":
        data["format"] = "keeplane-credential-v1"
    text = json.dumps(data)
    if change == "duplicate":
        text = text[:-1] + ',"client_id":"keeplane-cli-device"}'
    target.write_text(text)
    with pytest.raises(ProfileError):
        credential_refresh.refresh(path)
    assert not issuer.refresh_requests
