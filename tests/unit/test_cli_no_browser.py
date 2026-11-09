"""Spec 009 ST29 "No browser on the machine" (D161, ADR 028), journey case DEV-06.

The plain-English cases are in cli-no-browser-cases.md next to this file.
"""

import webbrowser

import pytest

from components.cli import browser_login, device_login, keeplane, sign_in_again
from components.cli.credential_profile import Credential, opened
from tests.unit.test_cli_browser_login import issuer  # noqa: F401

CODE_LINE = "Open {url}/oauth/confirm-device/ and enter code ABCD1234."


def found():
    return object()


def missing():
    raise webbrowser.Error("could not locate runnable browser")


# NB-01
@pytest.mark.parametrize(
    ("environ", "platform", "find", "expected"),
    [
        (
            {"SSH_CONNECTION": "10.0.0.2 5 10.0.0.1 22", "DISPLAY": ":0"},
            "linux",
            found,
            "ssh",
        ),
        ({"SSH_CLIENT": "10.0.0.2 5 22"}, "darwin", found, "ssh"),
        ({"SSH_TTY": "/dev/pts/1", "BROWSER": "firefox"}, "linux", found, "ssh"),
        ({}, "linux", found, "no display"),
        ({"DISPLAY": ""}, "freebsd14", found, "no display"),
        ({"DISPLAY": ":0"}, "linux", missing, "no browser"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, "linux", found, None),
        ({"DISPLAY": ":0"}, "linux", found, None),
        ({}, "darwin", found, None),
        ({}, "darwin", missing, "no browser"),
        ({}, "win32", found, None),
        ({"BROWSER": "my-browser %s"}, "linux", missing, None),
    ],
)
def test_nb_01_no_browser_over_ssh_without_a_display_or_with_none_found(
    environ, platform, find, expected
):
    assert browser_login.no_browser(environ, platform, find) == expected


@pytest.fixture
def no_browser(monkeypatch):
    """No browser can open; any attempt to open one fails the test."""
    monkeypatch.setattr(browser_login, "no_browser", lambda: "ssh")

    def never(url):
        raise AssertionError("no browser may be opened")

    monkeypatch.setattr(browser_login.webbrowser, "open", never)
    monkeypatch.setattr(device_login, "sleep", lambda seconds: None)


def login(monkeypatch, path, *arguments):
    monkeypatch.setattr(
        "sys.argv", ["keeplane", "login", "--profile", str(path), *arguments]
    )
    return keeplane.main()


# NB-02
def test_nb_02_login_with_no_browser_uses_the_device_code_without_a_flag(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    path = tmp_path / "profile"
    assert login(monkeypatch, path, "--server", issuer.url) == 0
    assert capsys.readouterr().out == (
        browser_login.NO_BROWSER
        + "\n"
        + CODE_LINE.format(url=issuer.url)
        + "\nSigned in to Keeplane.\n"
    )
    assert issuer.device_starts == 1 and not issuer.authorizations
    with opened(path) as profile:
        credential = profile.load()
    assert credential.client_id == device_login.CLIENT_ID
    assert credential.actor_id == issuer.actor
    assert issuer.device_code not in (path / "credential.json").read_text()


# NB-03
def test_nb_03_a_browser_that_fails_to_start_falls_back_to_the_device_code(
    issuer,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(browser_login, "no_browser", lambda: None)
    monkeypatch.setattr(browser_login.webbrowser, "open", lambda url: False)
    monkeypatch.setattr(device_login, "sleep", lambda seconds: None)
    path = tmp_path / "profile"
    assert login(monkeypatch, path, "--server", issuer.url) == 0
    assert capsys.readouterr().out == (
        browser_login.BROWSER
        + "\n"
        + browser_login.NO_BROWSER
        + "\n"
        + CODE_LINE.format(url=issuer.url)
        + "\nSigned in to Keeplane.\n"
    )
    assert not issuer.authorizations and not issuer.exchanges
    with opened(path) as profile:
        assert profile.load().client_id == device_login.CLIENT_ID


# NB-04
def test_nb_04_a_browser_that_raises_falls_back_without_showing_its_error(
    issuer,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(device_login, "sleep", lambda seconds: None)
    said = []

    def broken(url):
        raise OSError("secret browser detail " + url)

    assert (
        browser_login.login(
            issuer.url, tmp_path / "profile", browser=broken, announce=said.append
        )
        == "device"
    )
    assert not any("secret browser detail" in line for line in said)


# NB-05
def test_nb_05_a_signed_in_profile_is_refused_before_any_device_code(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    path = tmp_path / "profile"
    assert login(monkeypatch, path, "--server", issuer.url) == 0
    capsys.readouterr()
    assert login(monkeypatch, path, "--server", issuer.url) == 1
    assert "This profile is signed in" in capsys.readouterr().err
    assert issuer.device_starts == 1


# NB-06
def test_nb_06_device_flag_still_works_and_never_tries_a_browser(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    path = tmp_path / "profile"
    assert login(monkeypatch, path, "--device", "--server", issuer.url) == 0
    output = capsys.readouterr().out
    assert browser_login.NO_BROWSER not in output
    assert CODE_LINE.format(url=issuer.url) in output


# NB-07
def test_nb_07_login_without_server_uses_the_server_of_an_expired_sign_in(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    path = tmp_path / "profile"
    with opened(path, create=True) as profile:
        profile.save(
            Credential(issuer.url, issuer.actor, "kpc_" + "x" * 43, "kpr_" + "y" * 43)
        )
    checks = []

    def expired(server, path):
        checks.append(server)
        with opened(path) as profile:
            profile.forget()
        return server, "keeplane-cli"

    monkeypatch.setattr(
        sign_in_again,
        "clear_expired",
        lambda given: expired(issuer.url, given),
    )
    assert login(monkeypatch, path) == 0
    assert checks == [issuer.url]
    assert capsys.readouterr().out.endswith("Signed in to Keeplane.\n")
    with opened(path) as profile:
        assert profile.load().issuer == issuer.url


# NB-08
def test_nb_08_login_with_no_server_known_names_the_option_and_sends_nothing(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    assert login(monkeypatch, tmp_path / "profile") == 1
    assert capsys.readouterr().err == browser_login.NO_SERVER + "\n"
    assert issuer.device_starts == 0 and not issuer.authorizations


# NB-09
def test_nb_09_signing_in_again_with_no_browser_uses_the_device_code(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
):
    # ST29 + D190: the offer to sign in again works on a machine with no browser.
    path = tmp_path / "profile"
    with opened(path, create=True):
        pass
    monkeypatch.setattr(
        sign_in_again, "end_refused", lambda given: (issuer.url, "keeplane-cli")
    )
    said = []
    sign_in_again.sign_in(path, announce=said.append)
    assert said == [browser_login.NO_BROWSER, CODE_LINE.format(url=issuer.url)]
    with opened(path) as profile:
        assert profile.load().client_id == device_login.CLIENT_ID
