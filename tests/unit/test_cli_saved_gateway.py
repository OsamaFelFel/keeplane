"""The CLI saves the server's gateway address at sign-in (Spec 009 ST30, ADR 030).

Task 009-02b. Cases: tests/unit/cli-saved-gateway-cases.md (SG-01 to SG-07).
"""

import json
import stat
import uuid

import pytest

from components.cli import browser_login, credential_refresh, device_login, keeplane
from components.cli.credential_profile import Credential, ProfileError, opened
from components.cli.server_connection import ConnectionError
from tests.unit.test_cli_browser_login import issuer  # noqa: F401
from tests.unit.test_cli_device_login import clock  # noqa: F401

GATEWAY = "https://keeplane.example/v1"
# Wording decided by the associate product owner.
UNUSABLE = (
    "The server gave a gateway address the CLI can't use, so you aren't signed in. "
    "Ask your admin to check `KEEPLANE_GATEWAY_PUBLIC_URL`."
)


def credential(**changes):
    values = {
        "issuer": "https://keeplane.example",
        "actor_id": str(uuid.uuid4()),
        "access_token": "kpc_" + "a" * 43,
        "refresh_token": "kpr_" + "b" * 43,
    }
    return Credential(**{**values, **changes})


def stored(path):
    return json.loads((path / "credential.json").read_text())


def private(path):
    return stat.S_IMODE(path.stat().st_mode) == 0o700 and all(
        stat.S_IMODE(item.stat().st_mode) == 0o600 for item in path.iterdir()
    )


def browser_sign_in(issuer, path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(browser_login.webbrowser, "open", issuer.browser)
    monkeypatch.setattr(
        "sys.argv",
        ["keeplane", "login", "--server", issuer.url, "--profile", str(path)],
    )
    return keeplane.main()


# SG-01
@pytest.mark.parametrize("given", [GATEWAY, GATEWAY + "/", "http://127.0.0.1:5000/v1"])
def test_sg_01_browser_sign_in_saves_the_servers_gateway_privately(
    issuer,  # noqa: F811
    tmp_path,
    monkeypatch,
    given,
):
    issuer.session_extra = {"gateway_url": given}
    path = tmp_path / "profile"
    assert browser_sign_in(issuer, path, monkeypatch) == 0
    with opened(path) as profile:
        assert profile.load().gateway == given.rstrip("/")
    assert stored(path)["format"] == "keeplane-credential-v3"
    assert stored(path)["gateway"] == given.rstrip("/")
    assert private(path)


# SG-02
def test_sg_02_device_sign_in_saves_it_too(
    issuer,  # noqa: F811
    clock,  # noqa: F811
    tmp_path,
):
    issuer.session_extra = {"gateway_url": GATEWAY}
    path = tmp_path / "profile"
    device_login.login(issuer.url, path, announce=lambda message: None)
    with opened(path) as profile:
        saved = profile.load()
    assert (saved.client_id, saved.gateway) == ("keeplane-cli-device", GATEWAY)
    assert private(path)


# SG-03
@pytest.mark.parametrize("extra", [{"gateway_url": None}, {}])
def test_sg_03_no_address_saves_none_and_keeps_the_older_format(
    issuer,  # noqa: F811
    tmp_path,
    monkeypatch,
    extra,
):
    issuer.session_extra = extra
    path = tmp_path / "profile"
    assert browser_sign_in(issuer, path, monkeypatch) == 0
    with opened(path) as profile:
        assert profile.load().gateway is None
    assert stored(path)["format"] == "keeplane-credential-v2"
    assert "gateway" not in stored(path)


# SG-04
@pytest.mark.parametrize(
    "given",
    [
        "http://remote.example/v1",
        "https://keeplane.example",
        "https://keeplane.example/v1/chat/completions",
        "https://keeplane.example/v1?team=a",
        "https://user:secret@keeplane.example/v1",
        "https://keeplane.example:99999/v1",
        5,
    ],
)
def test_sg_04_an_address_the_cli_refuses_saves_nothing_and_revokes(
    issuer,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
    given,
):
    issuer.session_extra = {"gateway_url": given}
    path = tmp_path / "profile"
    with pytest.raises(ConnectionError) as error:
        browser_login.login(issuer.url, path, browser=issuer.browser)
    message = str(error.value)
    assert message == (
        "The server returned an invalid account." if given == 5 else UNUSABLE
    )
    assert not (path / "credential.json").exists()
    assert issuer.revocations == 1
    assert issuer.access not in message and str(given) not in message
    # The real command gives that message, claims no sign-in and exits 1.
    capsys.readouterr()
    assert browser_sign_in(issuer, tmp_path / "again", monkeypatch) == 1
    output = capsys.readouterr()
    assert output.err.strip() == message and "Signed in" not in output.out
    assert not (tmp_path / "again" / "credential.json").exists()


# SG-05
@pytest.mark.parametrize(
    ("before", "server", "after", "format"),
    [
        (None, GATEWAY, GATEWAY, "keeplane-credential-v3"),
        ("https://old.example/v1", GATEWAY, GATEWAY, "keeplane-credential-v3"),
        (GATEWAY, None, None, "keeplane-credential-v2"),
    ],
)
def test_sg_05_refresh_saves_the_servers_current_address(
    issuer,  # noqa: F811
    tmp_path,
    before,
    server,
    after,
    format,
):
    path = tmp_path / "profile"
    old = Credential(
        issuer.url,
        issuer.actor,
        "kpc_" + "o" * 43,
        "old_" + "r" * 43,
        gateway=before,
    )
    with opened(path, create=True) as profile:
        profile.save(old)
    issuer.expected_refresh = old.refresh_token
    issuer.session_extra = {"gateway_url": server}
    assert "refreshed" in credential_refresh.refresh(path)
    with opened(path) as profile:
        assert profile.load().gateway == after
    assert stored(path)["format"] == format
    assert private(path)


# SG-06
def test_sg_06_the_profile_keeps_only_a_checked_gateway(tmp_path):
    path = tmp_path / "profile"
    saved = credential(gateway=GATEWAY)
    assert saved.access_token not in repr(saved) and GATEWAY not in repr(saved)
    with opened(path, create=True) as profile:
        profile.save(saved)
        assert profile.load() == saved
        for unchecked in (GATEWAY + "/", "http://remote.example/v1", "", 5):
            with pytest.raises(ProfileError, match="invalid"):
                profile.save(credential(gateway=unchecked))
        assert profile.load() == saved
    target = path / "credential.json"
    good = stored(path)
    for change in (
        {"gateway": GATEWAY + "/"},
        {"gateway": None},
        {"gateway": "https://keeplane.example/v1?x=1"},
        {"format": "keeplane-credential-v2"},
    ):
        target.write_text(json.dumps(dict(good, **change)))
        with opened(path) as profile, pytest.raises(ProfileError, match="invalid"):
            profile.load()
    missing = dict(good)
    del missing["gateway"]
    target.write_text(json.dumps(missing))
    with opened(path) as profile, pytest.raises(ProfileError, match="invalid"):
        profile.load()
    # A v2 profile from before this task still loads, with no gateway.
    del missing["format"]
    target.write_text(json.dumps(dict(missing, format="keeplane-credential-v2")))
    with opened(path) as profile:
        assert profile.load().gateway is None


# SG-07
def test_sg_07_whoami_shows_the_account_not_the_gateway(
    issuer,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    issuer.session_extra = {"gateway_url": GATEWAY}
    path = tmp_path / "profile"
    assert browser_sign_in(issuer, path, monkeypatch) == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["keeplane", "whoami", "--profile", str(path)])
    assert keeplane.main() == 0
    assert set(json.loads(capsys.readouterr().out)) == {"id", "username", "role"}
