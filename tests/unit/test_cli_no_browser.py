"""Spec 009 ST29 "No browser on the machine" (D161, ADR 028), journey case DEV-06.

The plain-English cases are in cli-no-browser-cases.md next to this file.
"""

import stat
import webbrowser

import pytest

from components.cli import (
    browser_login,
    credential_profile,
    device_login,
    keeplane,
    sign_in_again,
)
from components.cli.credential_profile import Credential, opened, saved_server
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
    assert capsys.readouterr().err == (
        "Keeplane doesn't know your server yet. "
        "Run `keeplane login --server <address>`.\n"
    )
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


# NB-10
def test_nb_10_after_logout_a_plain_login_reuses_the_kept_server(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    path = tmp_path / "profile"
    assert login(monkeypatch, path, "--server", issuer.url) == 0
    monkeypatch.setattr("sys.argv", ["keeplane", "logout", "--profile", str(path)])
    assert keeplane.main() == 0
    assert issuer.revocations == 1
    assert {item.name for item in path.iterdir()} == {"lock", "server.json"}
    capsys.readouterr()
    assert login(monkeypatch, path) == 0
    assert capsys.readouterr().out.endswith("Signed in to Keeplane.\n")
    assert issuer.device_starts == 2
    with opened(path) as profile:
        assert profile.load().issuer == issuer.url


# NB-11
def test_nb_11_server_overrides_the_kept_server(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    path = tmp_path / "profile"
    with opened(path, create=True) as profile:
        profile.save_server("http://127.0.0.1:1")
    assert login(monkeypatch, path, "--server", issuer.url) == 0
    with opened(path) as profile:
        assert profile.load().issuer == issuer.url
    assert issuer.device_starts == 1


# NB-12
@pytest.mark.parametrize("how", ["timed out", "refused"])
def test_nb_12_a_browser_that_opened_but_did_not_finish_does_not_fall_back(
    issuer,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
    how,
):
    monkeypatch.setattr(browser_login, "no_browser", lambda: None)
    if how == "refused":
        issuer.callback_extra = {"error": "access_denied"}

        def browser(url):
            # The issuer's callback carries both a code and the error, so turn
            # it into a plain refusal with the matching state.
            from urllib.parse import parse_qs, urlencode, urlsplit

            target = urlsplit(url)
            state = parse_qs(target.query)["state"][0]
            redirect = parse_qs(target.query)["redirect_uri"][0]
            from urllib.request import ProxyHandler, build_opener

            with build_opener(ProxyHandler({})).open(
                redirect + "?" + urlencode({"state": state, "error": "access_denied"}),
                timeout=3,
            ):
                pass
            return True
    else:

        def browser(url):
            return True

    monkeypatch.setattr(browser_login.webbrowser, "open", browser)
    path = tmp_path / "profile"
    assert login(monkeypatch, path, "--server", issuer.url, "--timeout", "1") == 1
    output = capsys.readouterr()
    assert output.err == browser_login.UNFINISHED + "\n"
    assert browser_login.NO_BROWSER not in output.out
    assert issuer.device_starts == 0 and not issuer.exchanges
    assert not (path / "credential.json").exists()


def unusable_server_file(path, outside, how):
    """A signed-out profile whose server.json can't be used."""
    with opened(path, create=True):
        pass
    target = path / "server.json"
    good = b'{"format": "keeplane-server-v1", "server": "http://127.0.0.1:1"}'
    if how == "symlink":
        outside.write_bytes(good)
        outside.chmod(0o600)
        target.symlink_to(outside)
        return
    contents = {
        "malformed": b"[invalid",
        "extra key": good[:-1] + b', "x": 1}',
        "oversize": b"x" * 4097,
        "file mode": good,
    }
    target.write_bytes(contents[how])
    target.chmod(0o644 if how == "file mode" else 0o600)


BAD_SERVER_FILES = ["malformed", "extra key", "oversize", "file mode", "symlink"]


# NB-13
@pytest.mark.parametrize("how", BAD_SERVER_FILES)
def test_nb_13_an_unusable_kept_server_names_the_way_round_it(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
    how,
):
    path = tmp_path / "profile"
    unusable_server_file(path, tmp_path / "outside", how)
    assert login(monkeypatch, path) == 1
    assert capsys.readouterr().err == (
        "Keeplane can't use the server address it kept for this profile. "
        "Run `keeplane login --server <address>`, or `keeplane forget` to remove it.\n"
    )
    assert issuer.device_starts == 0 and not issuer.authorizations


# NB-14
@pytest.mark.parametrize("how", BAD_SERVER_FILES)
def test_nb_14_server_signs_in_and_replaces_the_unusable_file_unread(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
    how,
):
    path = tmp_path / "profile"
    unusable_server_file(path, tmp_path / "outside", how)

    def never(self):
        raise AssertionError("login --server must not read server.json")

    with monkeypatch.context() as patch:
        patch.setattr(credential_profile.Profile, "load_server", never)
        assert login(monkeypatch, path, "--server", issuer.url) == 0
    assert capsys.readouterr().out.endswith("Signed in to Keeplane.\n")
    # Replaced by the server just signed in to, with the same private write.
    target = path / "server.json"
    assert not target.is_symlink()
    assert stat.S_IMODE(target.lstat().st_mode) == 0o600
    assert saved_server(path) == issuer.url
    with opened(path) as profile:
        assert profile.load().issuer == issuer.url
    if how == "symlink":
        # A link is replaced, never what it points to.
        assert b"127.0.0.1:1" in (tmp_path / "outside").read_bytes()
    monkeypatch.setattr("sys.argv", ["keeplane", "logout", "--profile", str(path)])
    assert keeplane.main() == 0
    assert saved_server(path) == issuer.url


# NB-15
@pytest.mark.parametrize("how", BAD_SERVER_FILES)
def test_nb_15_forget_removes_an_unusable_kept_server(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
    how,
):
    path = tmp_path / "profile"
    unusable_server_file(path, tmp_path / "outside", how)
    monkeypatch.setattr("sys.argv", ["keeplane", "forget", "--profile", str(path)])
    assert keeplane.main() == 0
    assert capsys.readouterr().out == (
        "Removed the server address Keeplane couldn't use. "
        "Run `keeplane login --server <address>` to sign in.\n"
    )
    assert {item.name for item in path.iterdir()} == {"lock"}
    if how == "symlink":
        assert (tmp_path / "outside").exists()
    assert login(monkeypatch, path) == 1
    assert capsys.readouterr().err == browser_login.NO_SERVER + "\n"
    assert issuer.device_starts == 0


# NB-16
def test_nb_16_forget_when_signed_out_removes_a_usable_server(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
):
    path = tmp_path / "profile"
    with opened(path, create=True) as profile:
        profile.save_server(issuer.url)
    monkeypatch.setattr("sys.argv", ["keeplane", "forget", "--profile", str(path)])
    assert keeplane.main() == 0
    assert capsys.readouterr().out == (
        "Removed the saved server address. "
        "Run `keeplane login --server <address>` to sign in.\n"
    )
    assert {item.name for item in path.iterdir()} == {"lock"}
    assert keeplane.main() == 0
    assert capsys.readouterr().out == (
        "Keeplane has no saved sign-in or server address, "
        "so there's nothing to forget.\n"
    )
    decided = (
        "Delete the sign-in saved on this machine, or, once signed out, "
        "the saved server address."
    )
    for arguments in (["--help"], ["forget", "--help"]):
        monkeypatch.setattr("sys.argv", ["keeplane", *arguments])
        with pytest.raises(SystemExit):
            keeplane.main()
        assert decided in " ".join(capsys.readouterr().out.split())


# NB-17
@pytest.mark.parametrize("how", BAD_SERVER_FILES)
def test_nb_17_a_failed_sign_in_leaves_the_unusable_file_as_it_was(
    issuer,  # noqa: F811
    no_browser,
    tmp_path,
    monkeypatch,
    capsys,
    how,
):
    path = tmp_path / "profile"
    unusable_server_file(path, tmp_path / "outside", how)
    before = (path / "server.json").lstat()
    issuer.device_status = 500
    assert login(monkeypatch, path, "--server", issuer.url) == 1
    after = (path / "server.json").lstat()
    assert (after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns) == (
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    assert not (path / "credential.json").exists()
