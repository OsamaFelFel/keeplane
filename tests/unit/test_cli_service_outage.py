"""Task 009-15: a coding task stopped by an outage says so, not that the model is down.

Cases: tests/unit/cli-service-outage-cases.md (OUT-01 to OUT-14).
"""

import dataclasses
import json
import socket
import ssl
import subprocess
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from components.cli import coding, opencode_adapter, server_connection, usage_relay
from components.cli.credential_profile import opened
from tests.unit.test_cli_model_outage import api_error, failed_turn
from tests.unit.test_cli_project_profile import (  # noqa: F401
    code,
    connected,
    native_model,
    runtime,
)

GATEWAY_DOWN = (
    "Keeplane's gateway can't be reached right now, so this task stopped and "
    "nothing was sent. Try again in a few minutes, or ask your admin to check the "
    "gateway.\n"
)
SERVER_DOWN_MORE = (
    "Keeplane isn't available right now, so this task stopped and nothing more was "
    "sent. Try again in a few minutes, or ask your admin to check Keeplane.\n"
)


def through_relay(monkeypatch, fake):
    """A turn that sends one call through this turn's relay, as the runtime does."""

    def turn(command, **options):
        fake[1].append((command, options))
        config = json.loads(options["env"]["OPENCODE_CONFIG_CONTENT"])
        relay = config["providers"]["keeplane"]["settings"]["baseURL"]
        sent = Request(
            relay + "/chat/completions",
            json.dumps({"model": "coder", "messages": []}).encode(),
            {
                "Authorization": "Bearer " + options["env"]["KEEPLANE_RUNTIME_GRANT"],
                "Content-Type": "application/json",
            },
        )
        try:
            build_opener(ProxyHandler({})).open(sent, timeout=10).close()
            status = 200
        except HTTPError as error:
            status = error.code
            error.close()
        return subprocess.CompletedProcess(
            command, 0, json.dumps(api_error(status, "relay")) + "\n", ""
        )

    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)


def test_out_01_the_relay_counts_calls_the_gateway_never_answered():
    with usage_relay.Relay("http://127.0.0.1:9/v1", grant="grant") as relay:
        sent = Request(
            relay.url + "/chat/completions",
            b"{}",
            {"Authorization": "Bearer grant", "Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as answer:
            build_opener(ProxyHandler({})).open(sent, timeout=10)
        assert answer.value.code == 502
        answer.value.close()
    assert relay.unreachable == 1 and relay.usage() == {}


def test_out_02_gateway_down_says_so_and_nothing_was_sent(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
):
    # The test's gateway address resolves to nothing: the relay can't reach it.
    connected.alternatives = ["general"]
    through_relay(monkeypatch, runtime)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    output = capsys.readouterr()
    assert GATEWAY_DOWN in output.err
    assert "is unavailable right now" not in output.err
    # Not a model problem: no alternatives are asked for.
    assert not any("model-alternatives" in row[1] for row in connected.calls)


def test_out_03_gateway_down_after_earlier_calls_says_nothing_more(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
):
    original = opencode_adapter.run

    def earlier_calls(*args, **kwargs):
        result = original(*args, **kwargs)
        result.usage = {
            "coder": {
                "requests": 1,
                "input_tokens": 3,
                "output_tokens": 1,
                "requests_without_usage": 0,
            }
        }
        return result

    through_relay(monkeypatch, runtime)
    monkeypatch.setattr(coding.opencode_adapter, "run", earlier_calls)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert "stopped and nothing more was sent" in capsys.readouterr().err


def with_keeplane_down(connected, runtime, monkeypatch, tmp_path, capsys, failed, down):  # noqa: F811
    """One failed turn after an earlier call, then Keeplane goes down; stderr."""
    original = opencode_adapter.run

    def turn_then_down(*args, **kwargs):
        result = original(*args, **kwargs)
        result.usage = {
            "coder": {
                "requests": 1,
                "input_tokens": 3,
                "output_tokens": 1,
                "requests_without_usage": 0,
            }
        }
        if down is None:
            # Nothing answers at Keeplane's address any more.
            monkeypatch.setattr(coding, "account", unreachable)
        else:
            connected.status = down
        return result

    def unreachable(*_):
        raise coding.Unreachable("Cannot reach Keeplane securely.")

    failed_turn(monkeypatch, runtime, failed)
    monkeypatch.setattr(coding.opencode_adapter, "run", turn_then_down)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    return capsys.readouterr().err


@pytest.mark.parametrize(
    "status,reason",
    [
        # agentgateway's own refusal when Keeplane's check doesn't answer.
        (403, "external authorization failed"),
        # Keeplane's check passed on by the gateway, with its storage down.
        (503, '{"error": "Keeplane storage is unavailable; contact your operator"}'),
        (503, '{"error": "Gateway authorization is unavailable"}'),
    ],
)
@pytest.mark.parametrize("down", [503, None])
def test_out_04_keeplane_down_behind_the_gateway_says_so(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
    status,
    reason,
    down,
):
    """The gateway refused before any model was tried: Keeplane's check couldn't run."""
    err = with_keeplane_down(
        connected,
        runtime,
        monkeypatch,
        tmp_path,
        capsys,
        api_error(status, reason),
        down,
    )
    assert SERVER_DOWN_MORE in err
    assert "is unavailable right now" not in err and "expired" not in err


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
@pytest.mark.parametrize("down", [503, None])
def test_out_07_a_model_that_was_tried_keeps_its_st16_message(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
    status,
    down,
):
    """D177: the model was tried and failed, so ST16 stays even while Keeplane is down."""
    err = with_keeplane_down(
        connected, runtime, monkeypatch, tmp_path, capsys, api_error(status), down
    )
    assert "coder is unavailable right now" in err
    assert "Keeplane isn't available" not in err


@pytest.mark.parametrize("status", [403, 503])
def test_out_05_a_refusal_with_keeplane_answering_keeps_its_own_message(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
    status,
):
    failed_turn(monkeypatch, runtime, api_error(status))
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    err = capsys.readouterr().err
    assert "Keeplane isn't available" not in err
    assert ("coder is unavailable right now" in err) == (status == 503)


def test_out_06_an_expired_sign_in_still_wins(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
):
    failed_turn(monkeypatch, runtime, api_error(401, "Sign in to Keeplane"))
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    err = capsys.readouterr().err
    assert "Your Keeplane sign-in has expired" in err
    assert "isn't available" not in err and "can't be reached" not in err


START_UNAVAILABLE = (
    "Keeplane isn't available right now, so nothing was sent. Try again in a few "
    "minutes, or ask your admin to check Keeplane.\n"
)


@pytest.mark.parametrize("status", [502, 503, 504])
def test_out_08_keeplane_unavailable_before_the_task_starts(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
    status,
):
    connected.status = status
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err == START_UNAVAILABLE
    assert not runtime[1]


def test_out_09_no_connection_to_keeplane_before_the_task_starts(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
):
    with opened(connected.path) as profile:
        old = profile.load()
        profile.save(dataclasses.replace(old, issuer="http://127.0.0.1:9"))
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err == START_UNAVAILABLE
    assert not runtime[1]


def test_out_10_a_certificate_problem_keeps_its_own_message(monkeypatch):
    class Opener:
        def open(self, *args, **kwargs):
            raise URLError(ssl.SSLCertVerificationError("certificate verify failed"))

    monkeypatch.setattr(server_connection, "build_opener", lambda *a: Opener())
    with pytest.raises(server_connection.ConnectionError) as error:
        server_connection.account("https://keeplane.example", "kpc_" + "a" * 43)
    assert not isinstance(error.value, server_connection.Unreachable)
    assert str(error.value) == (
        "Cannot reach Keeplane securely; check the server and certificate "
        "configuration."
    )


# Before the task starts, nothing at all was sent.
GATEWAY_DOWN_AT_START = GATEWAY_DOWN


@pytest.mark.parametrize("route", ["models", "choice"])
@pytest.mark.parametrize("gateway_up", [False, True])
def test_out_11_keeplane_cant_choose_a_model_because_the_gateway_is_down(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
    route,
    gateway_up,
):
    """Keeplane answered the sign-in check, then couldn't choose a model (503)."""
    setattr(connected, route + "_status", 503)
    probed = []
    monkeypatch.setattr(
        coding, "gateway_answers", lambda gateway: probed.append(gateway) or gateway_up
    )
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err == (
        START_UNAVAILABLE if gateway_up else GATEWAY_DOWN_AT_START
    )
    assert probed == ["https://gateway.test/v1"]
    assert not runtime[1]


def test_out_12_keeplane_down_from_the_sign_in_check_never_blames_the_gateway(
    connected,  # noqa: F811 - imported pytest fixture
    runtime,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    capsys,
):
    connected.status = 503
    monkeypatch.setattr(coding, "gateway_answers", lambda gateway: False)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err == START_UNAVAILABLE


def test_out_13_keeplanes_gateway_reason_is_enough_without_a_probe(monkeypatch):
    monkeypatch.setattr(coding, "gateway_answers", lambda gateway: True)
    error = server_connection.KeeplaneUnavailable("x", 503, coding.GATEWAY_REASON)
    assert coding.start_outage(error, "https://gw.test/v1", True) + "\n" == (
        GATEWAY_DOWN_AT_START
    )
    other = server_connection.KeeplaneUnavailable("x", 503, "Something else")
    assert coding.start_outage(other, "https://gw.test/v1", True) + "\n" == (
        START_UNAVAILABLE
    )
    # A 502 or 504 is a proxy in front of Keeplane, not Keeplane's own answer.
    for status in (502, 504):
        error = server_connection.KeeplaneUnavailable("x", status, None)
        monkeypatch.setattr(coding, "gateway_answers", lambda gateway: False)
        assert coding.start_outage(error, "https://gw.test/v1", True) + "\n" == (
            START_UNAVAILABLE
        )


def test_out_14_the_gateway_probe_only_connects():
    with socket.socket() as listening:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        port = listening.getsockname()[1]
        assert coding.gateway_answers(f"http://127.0.0.1:{port}/v1")
    # Nothing listens on the discard port.
    assert not coding.gateway_answers("http://127.0.0.1:9/v1")
    assert not coding.gateway_answers("https://gateway.invalid/v1", timeout=2)
