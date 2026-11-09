"""Spec 009 ST29: an expired sign-in sends nothing more and offers to sign in again.

The plain-English cases are in cli-sign-in-again-cases.md next to this file.
"""

import io
import json
import subprocess
import sys
import uuid

import pytest

from components.cli import (
    browser_login,
    device_login,
    keeplane,
    opencode_adapter,
    sign_in_again,
)
from components.cli.credential_profile import Credential, opened
from components.cli.server_connection import SignInExpired
from tests.unit.test_cli_project_profile import (  # noqa: F401
    code,
    command,
    connected,
    runtime,
)

SCRIPT = (
    "Your Keeplane sign-in has expired, so nothing was sent. "
    "Run `keeplane login` to sign in again.\n"
)
OFFER = (
    "Your Keeplane sign-in has expired, so nothing was sent. Sign in again now? [Y/n] "
)
OFFER_MORE = (
    "Your Keeplane sign-in has expired, so nothing more was sent. "
    "Sign in again now? [Y/n] "
)
START = "Signed in. Start the task now? [Y/n] "
DECLINED = "Run `keeplane login` to sign in again.\n"
NOT_STARTED = (
    "You're signed in. The task wasn't started, so nothing was sent. "
    "Run it again when you're ready.\n"
)
NOT_CONTINUED = (
    "You're signed in. The task wasn't continued, so nothing more was sent. "
    "Run it again when you're ready.\n"
)
EXPIRED_READ = (
    "Your Keeplane sign-in has expired. Run `keeplane login` to sign in again.\n"
)
EXPIRED_NOT_SAVED = (
    "Your Keeplane sign-in has expired. Nothing was saved. "
    "Run `keeplane login` to sign in again.\n"
)
SIGNED_OUT_SHORT = "You're signed out of Keeplane. Run `keeplane login` to sign in.\n"
SIGNED_OUT = (
    "You're signed out of Keeplane, so nothing was sent. "
    "Run `keeplane login` to sign in.\n"
)
NEW_ACCESS = "kpc_" + "n" * 43


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def terminal(monkeypatch):
    """A terminal on stdin and stderr; the test sets the developer's answers."""

    def answer(*lines):
        monkeypatch.setattr(
            sys, "stdin", Terminal("".join(line + "\n" for line in lines))
        )
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True, raising=False)

    return answer


@pytest.fixture
def sign_ins(connected, monkeypatch):  # noqa: F811
    """Signing in again saves a new credential that the server accepts."""
    calls = []

    def login(kind):
        def run(server, path, *, timeout=120, **options):
            calls.append((kind, server, str(path), timeout))
            assert not (connected.path / "credential.json").exists()
            with opened(path) as profile:
                profile.save(
                    Credential(
                        server,
                        connected.actor,
                        NEW_ACCESS,
                        "s" * 32,
                        device_login.CLIENT_ID if kind == "device" else "keeplane-cli",
                    )
                )
            connected.access, connected.status = NEW_ACCESS, 200

        return run

    monkeypatch.setattr(browser_login, "login", login("browser"))
    monkeypatch.setattr(device_login, "login", login("device"))
    return calls


def gateway_events(monkeypatch, runtime, *events):  # noqa: F811
    def turn(command, **options):
        runtime[1].append((command, options))
        return subprocess.CompletedProcess(
            command, 0, "".join(json.dumps(event) + "\n" for event in events), ""
        )

    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)


UNAUTHORIZED = {
    "type": "error",
    "error": {
        "name": "APIError",
        "data": {"message": "Unauthorized", "statusCode": 401, "isRetryable": False},
    },
}


def paths(connected):  # noqa: F811
    return [row[1] for row in connected.calls]


def test_exp_01_in_a_script_an_expired_sign_in_exits_1_and_names_login(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
):
    connected.status = 401
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    output = capsys.readouterr()
    assert output.err == SCRIPT and output.out == ""
    # Nothing reaches the gateway once the server has said 401.
    assert not runtime[1] and paths(connected) == ["/api/runtime/session"]
    assert not sign_ins and (connected.path / "credential.json").exists()


def test_exp_02_yes_signs_in_with_the_saved_server_then_asks_before_starting(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
    terminal,
):
    connected.status = 401
    terminal("", "y")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    output = capsys.readouterr()
    assert output.err == (
        OFFER
        + "Opening Keeplane sign-in in your browser.\n"
        + START
        + "Answered by coder.\n"
    )
    assert output.out == "Coding finished.\n"
    assert sign_ins == [("browser", connected.issuer, str(connected.path), 120)]
    assert len(runtime[1]) == 1  # The task starts only after the second yes.
    assert runtime[1][0][1]["env"]["KEEPLANE_RUNTIME_GRANT"] == NEW_ACCESS
    with opened(connected.path) as profile:
        assert profile.load().access_token == NEW_ACCESS


@pytest.mark.parametrize(
    "answer", ["n", "no", "later", None], ids=["n", "no", "other", "eof"]
)
def test_exp_03_declining_to_sign_in_again_exits_1_and_sends_nothing(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
    terminal,
    answer,
):
    connected.status = 401
    terminal(*([] if answer is None else [answer]))
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    error = capsys.readouterr().err
    assert error.startswith(OFFER) and error.endswith(DECLINED)
    assert not sign_ins and not runtime[1]
    assert paths(connected) == ["/api/runtime/session"]
    assert (
        connected.path / "credential.json"
    ).exists()  # Kept, so scripts still say expired.


def test_exp_04_declining_to_start_after_signing_in_starts_nothing(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
    terminal,
):
    connected.status = 401
    terminal("y", "n")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    error = capsys.readouterr().err
    assert (
        error
        == OFFER + "Opening Keeplane sign-in in your browser.\n" + START + NOT_STARTED
    )
    assert len(sign_ins) == 1 and not runtime[1]


def test_exp_04b_declining_to_continue_after_earlier_steps_says_nothing_more(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
    terminal,
):
    gateway_events(monkeypatch, runtime, {"type": "step_start"}, UNAUTHORIZED)
    terminal("y", "n")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    error = capsys.readouterr().err
    assert error.startswith(OFFER_MORE) and error.endswith(START + NOT_CONTINUED)
    assert len(sign_ins) == 1 and len(runtime[1]) == 1


def test_exp_05_a_device_sign_in_signs_in_again_with_the_device_code(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
    terminal,
):
    with opened(connected.path) as profile:
        profile.save(
            Credential(
                connected.issuer,
                connected.actor,
                connected.access,
                connected.refresh,
                device_login.CLIENT_ID,
            )
        )
    connected.status = 401
    terminal("yes", "YES")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    assert [row[0] for row in sign_ins] == ["device"] and len(runtime[1]) == 1
    assert "browser" not in capsys.readouterr().err


def test_exp_06_a_gateway_401_after_earlier_steps_says_nothing_more_was_sent(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
):
    step = {"type": "text", "part": {"text": "Reading math.py for " + connected.access}}
    gateway_events(monkeypatch, runtime, step, UNAUTHORIZED)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    output = capsys.readouterr()
    assert output.err == (
        "Your Keeplane sign-in has expired, so nothing more was sent. "
        "Run `keeplane login` to sign in again.\n"
    )
    assert "Reading math.py" in output.out and connected.access not in output.out
    assert len(runtime[1]) == 1
    # Nothing more is sent: no request for other models after the 401.
    assert all("/model-alternatives" not in path for path in paths(connected))


def test_exp_07_a_gateway_401_on_the_first_step_says_nothing_was_sent(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
):
    gateway_events(monkeypatch, runtime, UNAUTHORIZED)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    output = capsys.readouterr()
    assert output.err == SCRIPT and json.loads(output.out)["type"] == "error"
    assert len(runtime[1]) == 1


def test_exp_08_in_a_terminal_a_gateway_401_offers_more_and_runs_again_on_yes(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
    terminal,
):
    gateway_events(monkeypatch, runtime, {"type": "step_start"}, UNAUTHORIZED)
    original = opencode_adapter.coding_turn

    def then_expired(command, **options):
        connected.status = 401  # The server agrees once the gateway has refused it.
        return original(command, **options)

    monkeypatch.setattr(opencode_adapter, "coding_turn", then_expired)
    terminal("y", "y")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    error = capsys.readouterr().err
    assert error.startswith(OFFER_MORE) and START in error
    assert len(sign_ins) == 1 and len(runtime[1]) == 2
    # The second run was refused too: it is reported, not offered again.
    assert error.endswith(
        "nothing more was sent. Run `keeplane login` to sign in again.\n"
    )
    assert error.count("Sign in again now?") == 1


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["whoami"], EXPIRED_READ),
        (["models", "--project", "P"], EXPIRED_READ),
        (["keys", "status", "--model", "coder"], EXPIRED_READ),
        (["keys", "set", "--model", "coder", "--key-stdin"], EXPIRED_NOT_SAVED),
        (["keys", "remove", "--model", "coder"], EXPIRED_NOT_SAVED),
        (["register-project", "--project", "P"], SCRIPT),
    ],
    ids=["whoami", "models", "keys-status", "keys-set", "keys-remove", "register"],
)
def test_exp_09_other_commands_say_the_sign_in_has_expired(
    connected,  # noqa: F811
    monkeypatch,
    capsys,
    arguments,
    expected,
):
    connected.status = 401
    monkeypatch.setattr(sys, "stdin", io.StringIO("sk-synthetic-provider-key\n"))
    head = arguments[:2] if arguments[0] == "keys" else arguments[:1]
    rest = [
        str(uuid.uuid4()) if value == "P" else value for value in arguments[len(head) :]
    ]
    monkeypatch.setattr(
        "sys.argv", ["keeplane", *head, "--profile", str(connected.path), *rest]
    )
    assert keeplane.main() == 1
    assert capsys.readouterr().err == expected
    assert paths(connected) == ["/api/runtime/session"]


def test_exp_10_login_replaces_an_expired_sign_in_but_not_a_current_one(
    connected,  # noqa: F811
    monkeypatch,
    capsys,
    sign_ins,
):
    connected.status = 401
    assert command(monkeypatch, connected, "login", "--server", connected.issuer) == 0
    assert capsys.readouterr().out.endswith("Signed in to Keeplane.\n")
    assert [row[0] for row in sign_ins] == ["browser"]
    with opened(connected.path) as profile:
        assert profile.load().access_token == NEW_ACCESS


def test_exp_11_login_still_refuses_a_sign_in_the_server_accepts(
    connected,  # noqa: F811
    monkeypatch,
    capsys,
):
    opened_browser = []
    monkeypatch.setattr(browser_login.webbrowser, "open", opened_browser.append)
    assert command(monkeypatch, connected, "login", "--server", connected.issuer) == 1
    assert "This profile is signed in" in capsys.readouterr().err
    assert not opened_browser
    with opened(connected.path) as profile:
        assert profile.load().access_token == connected.access


def test_exp_13_a_gateway_401_the_server_still_accepts_ends_that_sign_in_first(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    sign_ins,
    terminal,
):
    # Only the gateway refused it. On yes the server is asked to revoke it, so
    # signing in again works instead of "This profile is signed in".
    old, runs = connected.access, runtime[1]

    def turn(command, **options):
        runs.append((command, options))
        stdout = (
            json.dumps(UNAUTHORIZED) + "\n" if len(runs) == 1 else "Coding finished.\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)
    terminal("y", "y")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    output = capsys.readouterr()
    assert (
        output.err.startswith(OFFER) and "This profile is signed in" not in output.err
    )
    assert output.out.endswith("Coding finished.\n")
    revoked = [row for row in connected.calls if row[0] == "DELETE"]
    assert len(revoked) == 1 and revoked[0][2]["Authorization"] == "Bearer " + old
    assert len(sign_ins) == 1 and len(runs) == 2
    assert runs[1][1]["env"]["KEEPLANE_RUNTIME_GRANT"] == NEW_ACCESS


def test_exp_14_cancelling_the_new_sign_in_leaves_you_signed_out(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    terminal,
):
    def cancelled(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(browser_login, "login", cancelled)
    connected.status = 401
    terminal("y")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 130
    assert not (connected.path / "credential.json").exists() and not runtime[1]
    capsys.readouterr()
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err == SIGNED_OUT


def test_exp_15_an_unreachable_server_stops_signing_in_again_and_keeps_the_sign_in(
    connected,  # noqa: F811
    sign_ins,
):
    with opened(connected.path) as profile:
        profile.save(
            Credential(
                "http://127.0.0.1:9",
                connected.actor,
                connected.access,
                connected.refresh,
            )
        )
    with pytest.raises(sign_in_again.ConnectionError):
        sign_in_again.sign_in(connected.path, announce=lambda message: None)
    assert not sign_ins and (connected.path / "credential.json").exists()


def test_exp_12_an_unreachable_server_keeps_the_saved_sign_in(connected):  # noqa: F811
    with opened(connected.path) as profile:
        profile.save(
            Credential(
                "http://127.0.0.1:9",
                connected.actor,
                connected.access,
                connected.refresh,
            )
        )
    assert sign_in_again.clear_expired(connected.path) == (
        "http://127.0.0.1:9",
        "keeplane-cli",
    )
    assert (connected.path / "credential.json").exists()


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["code", "anything"], SIGNED_OUT),
        (["models"], SIGNED_OUT),
        (["usage"], SIGNED_OUT),
        (["keys", "list"], SIGNED_OUT),
        (["keys", "status", "--model", "coder"], SIGNED_OUT),
        (["register-project"], SIGNED_OUT),
        (["whoami"], SIGNED_OUT_SHORT),
        (["refresh"], SIGNED_OUT_SHORT),
    ],
    ids=[
        "code",
        "models",
        "usage",
        "keys-list",
        "keys-status",
        "register",
        "whoami",
        "refresh",
    ],
)
def test_out_01_signed_out_sends_nothing_and_says_how_to_sign_in(
    connected,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    arguments,
    expected,
):
    assert command(monkeypatch, connected, "logout") == 0
    capsys.readouterr()
    connected.calls.clear()
    monkeypatch.setattr(
        "sys.argv",
        ["keeplane", *arguments[:2], "--profile", str(connected.path), *arguments[2:]],
    )
    assert keeplane.main() == 1
    assert capsys.readouterr().err == expected
    assert connected.calls == []


def test_out_03_logout_when_already_signed_out_says_so_and_succeeds(
    connected,  # noqa: F811
    monkeypatch,
    capsys,
):
    assert command(monkeypatch, connected, "logout") == 0
    capsys.readouterr()
    connected.calls.clear()
    assert command(monkeypatch, connected, "logout") == 0
    assert capsys.readouterr().out == "You're already signed out of Keeplane.\n"
    assert connected.calls == []


def test_out_02_never_signed_in_is_signed_out_with_no_offer(
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    terminal,
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    terminal("y")
    monkeypatch.setattr(
        "sys.argv", ["keeplane", "code", "--directory", str(tmp_path), "anything"]
    )
    assert keeplane.main() == 1
    assert capsys.readouterr().err == SIGNED_OUT
    assert not runtime[1] and not (tmp_path / "config").exists()


def test_the_expired_error_keeps_status_401_for_existing_callers():
    error = SignInExpired()
    assert error.status == 401 and str(error) + "\n" == SCRIPT
    assert SignInExpired(more=True).notice.endswith("so nothing more was sent.")


def test_answers():
    stderr = io.StringIO()
    assert sign_in_again.ask("Q? ", stdin=io.StringIO("\n"), stderr=stderr)
    assert sign_in_again.ask("Q? ", stdin=io.StringIO(" Y \n"), stderr=stderr)
    assert not sign_in_again.ask("Q? ", stdin=io.StringIO("nope\n"), stderr=stderr)
    assert not sign_in_again.ask("Q? ", stdin=io.StringIO(""), stderr=stderr)
    assert not sign_in_again.in_terminal(io.StringIO(), Terminal())
    assert not sign_in_again.in_terminal(Terminal(), io.StringIO())
    assert sign_in_again.in_terminal(Terminal(), Terminal())
