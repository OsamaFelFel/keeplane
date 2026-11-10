"""Task 009-15: a coding task stopped by an outage says so, not that the model is down.

Cases: tests/unit/cli-service-outage-cases.md (OUT-01 to OUT-07).
"""

import json
import subprocess
import uuid
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from components.cli import coding, opencode_adapter, usage_relay
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
