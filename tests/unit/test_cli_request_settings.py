"""Spec 004 ST26: request settings set per model reach the gateway unchanged.

Cases: tests/unit/cli-request-settings-cases.md (REQ-01 to REQ-07).
"""

import json
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import ClassVar

import pytest

from components.cli import opencode_adapter, request_settings, settings_file
from tests.unit.test_cli_project_profile import code, connected, runtime  # noqa: F401
from tests.unit.test_cli_usage import GRANT, call

SETTINGS = {
    "temperature": 0.37,
    "top_p": 0.81,
    "max_tokens": 777,
    "reasoning_effort": "low",
}


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


class Gateway(BaseHTTPRequestHandler):
    """A stand-in gateway that keeps every request body it receives."""

    protocol_version = "HTTP/1.1"
    seen: ClassVar[list] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        type(self).seen.append(self.rfile.read(int(self.headers["Content-Length"])))
        payload = b'{"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def gateway():
    Gateway.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}/v1")
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def turn(tmp_path, monkeypatch, gateway_url="https://gateway.test/v1", send=None):
    """Run one stand-in turn; return the runtime's settings, or None if not started."""
    seen = {}

    def version(command, **options):
        seen["version"] = True
        return subprocess.CompletedProcess(command, 0, "opencode v2.0.27\n", "")

    def native(command, **options):
        seen["config"] = json.loads(options["env"]["OPENCODE_CONFIG_CONTENT"])
        if send:
            send(seen["config"])
        return subprocess.CompletedProcess(command, 0, "", "")

    binary = tmp_path / "runtime"
    binary.touch()
    monkeypatch.setattr(opencode_adapter.subprocess, "run", version)
    monkeypatch.setattr(opencode_adapter, "coding_turn", native)
    opencode_adapter.run(
        str(binary), str(tmp_path), gateway_url, "coder", "Fix it.", GRANT
    )
    return seen.get("config")


def model_entry(config):
    return config["providers"]["keeplane"]["models"]["coder"]


USAGE_FLAG = {"supportsUsageInStreaming": True}
# With max_tokens, the runtime's own output cap is written as max_tokens too,
# so the body's value replaces it and no max_completion_tokens is sent.
OWN_CAP = {**USAGE_FLAG, "maxTokensField": "max_tokens"}


# REQ-01 The settings saved for a model become the runtime's request body
# overlay for that model, with the same names and values.
def test_req_01_saved_settings_become_the_model_options(tmp_path, monkeypatch):
    settings_file.set_request_settings("coder", SETTINGS)
    settings_file.set_request_settings("other", {"temperature": 1.5})
    config = turn(tmp_path, monkeypatch)
    assert model_entry(config) == {
        "name": "coder",
        "compatibility": OWN_CAP,
        "body": SETTINGS,
    }
    opencode_adapter.check_settings(
        config, config["providers"]["keeplane"]["settings"]["baseURL"]
    )


# REQ-01 Each setting on its own, and none at all: Keeplane adds nothing.
@pytest.mark.parametrize("name", sorted(SETTINGS))
def test_req_01_one_setting(tmp_path, monkeypatch, name):
    settings_file.set_request_settings("coder", {name: SETTINGS[name]})
    config = turn(tmp_path, monkeypatch)
    assert model_entry(config)["body"] == {name: SETTINGS[name]}
    # Only max_tokens moves the runtime's own cap onto the same field.
    assert model_entry(config)["compatibility"] == (
        OWN_CAP if name == "max_tokens" else USAGE_FLAG
    )
    opencode_adapter.check_settings(
        config, config["providers"]["keeplane"]["settings"]["baseURL"]
    )


@pytest.mark.parametrize("saved", [None, {}])
def test_req_01_no_settings_add_nothing(tmp_path, monkeypatch, saved):
    if saved is not None:
        settings_file.set_request_settings("coder", saved)
    entry = model_entry(turn(tmp_path, monkeypatch))
    assert "body" not in entry and entry["compatibility"] == USAGE_FLAG


# REQ-02 Through the turn's usage relay, the gateway receives the request
# body byte for byte, settings included.
def test_req_02_settings_reach_the_gateway_unchanged(tmp_path, monkeypatch, gateway):
    settings_file.set_request_settings("coder", SETTINGS)
    sent = []

    def send(config):
        # What the runtime does: lay the model's body over its own request.
        body = {
            "model": "coder",
            "stream": False,
            "messages": [{"role": "user", "content": "x"}],
            **model_entry(config)["body"],
        }
        sent.append(json.dumps(body).encode())
        status, _ = call(
            config["providers"]["keeplane"]["settings"]["baseURL"], body=sent[-1]
        )
        assert status == 200

    turn(tmp_path, monkeypatch, gateway.url, send)
    assert Gateway.seen == sent
    received = json.loads(Gateway.seen[0])
    assert {name: received[name] for name in SETTINGS} == SETTINGS


REFUSED = {
    # Provider, address, key and plugin settings, each with the reason.
    "provider": ("provider", "openai"),
    "package": ("provider", "@opencode/ai/providers/openai"),
    "baseURL": ("address", "https://api.openai.com/v1"),
    "api_base": ("address", "https://api.openai.com/v1"),
    "apiKey": ("key", "sk-synthetic"),
    "api_key": ("key", "sk-synthetic"),
    "headers": ("key", {"Authorization": "Bearer x"}),
    "env": ("key", ["OPENAI_API_KEY"]),
    "plugins": ("plugin", ["./plugin"]),
    "mcp": ("plugin", {"remote": {}}),
}


# REQ-03 A provider, address, key or plugin setting is refused with a clear
# message, and nothing starts.
@pytest.mark.parametrize("name", sorted(REFUSED))
def test_req_03_routing_settings_are_refused(tmp_path, monkeypatch, name):
    kind, value = REFUSED[name]
    settings_file.set_request_settings("coder", {"temperature": 0.2, name: value})
    with pytest.raises(request_settings.RequestSettingsError) as refused:
        turn(tmp_path, monkeypatch)
    message = str(refused.value)
    assert f'"{name}"' in message and " " + kind + " setting" in message
    assert "provider, address, key and plugin settings aren't allowed" in message
    assert "sk-synthetic" not in message


# REQ-04 Any other setting Keeplane doesn't pass on is refused, naming the
# four it does.
@pytest.mark.parametrize(
    "name",
    ["seed", "stop", "top_k", "frequency_penalty", "maxOutputTokens", "temperature "],
)
def test_req_04_unreviewed_settings_are_refused(name):
    with pytest.raises(
        request_settings.RequestSettingsError,
        match="Use only temperature, top_p, max_tokens or reasoning_effort",
    ):
        request_settings.check("coder", {name: 1})


# REQ-05 A value a setting can't have is refused, with the values it can.
@pytest.mark.parametrize(
    "name,value,hint",
    [
        ("temperature", -0.1, "from 0 to 2"),
        ("temperature", 2.5, "from 0 to 2"),
        ("temperature", "0.2", "from 0 to 2"),
        ("temperature", True, "from 0 to 2"),
        ("temperature", float("nan"), "from 0 to 2"),
        ("top_p", 1.01, "from 0 to 1"),
        ("top_p", None, "from 0 to 1"),
        ("max_tokens", 0, "whole number"),
        ("max_tokens", 1.5, "whole number"),
        ("max_tokens", 1_000_001, "whole number"),
        ("reasoning_effort", "maximum", "one of none"),
        ("reasoning_effort", 3, "one of none"),
    ],
)
def test_req_05_values_are_checked(name, value, hint):
    with pytest.raises(request_settings.RequestSettingsError, match=hint):
        request_settings.check("coder", {name: value})


@pytest.mark.parametrize(
    "name,value",
    [
        ("temperature", 0),
        ("temperature", 2),
        ("temperature", 1),
        ("top_p", 0),
        ("top_p", 1.0),
        ("max_tokens", 1),
        ("max_tokens", 1_000_000),
        *[
            ("reasoning_effort", effort)
            for effort in request_settings.REASONING_EFFORTS
        ],
    ],
)
def test_req_05_values_in_range_pass_unchanged(name, value):
    checked = request_settings.check("coder", {name: value})
    assert checked == {name: value} and type(checked[name]) is type(value)


# REQ-06 The runtime settings check stays strict: the model entry may add
# only a body of the reviewed settings with valid values.
def runtime_settings(body, compatibility=None):
    if compatibility is None:
        has_cap = isinstance(body, dict) and "max_tokens" in body
        compatibility = OWN_CAP if has_cap else USAGE_FLAG
    config = {
        "providers": {
            "keeplane": {
                "package": opencode_adapter.PROVIDER_PACKAGE,
                "env": ["KEEPLANE_RUNTIME_GRANT"],
                "settings": {"baseURL": "http://127.0.0.1:41234/v1"},
                "models": {
                    "coder": {
                        "name": "coder",
                        "compatibility": compatibility,
                        "body": body,
                    }
                },
            }
        },
        "model": "keeplane/coder",
        "share": "disabled",
        "snapshots": False,
        "websearch": False,
        "plugins": list(opencode_adapter.DISABLED_BUILTINS)
        + list(opencode_adapter.DISABLED_PROVIDERS),
        "experimental": {
            "policies": [dict(row) for row in opencode_adapter.PROVIDER_POLICIES]
        },
    }
    return config


@pytest.mark.parametrize(
    "body", [dict(SETTINGS), {"max_tokens": 777}, {"temperature": 0.2}]
)
def test_req_06_check_accepts_the_reviewed_body(body):
    opencode_adapter.check_settings(runtime_settings(body), "http://127.0.0.1:41234/v1")


# REQ-06 The output-cap flag comes only with max_tokens, and only as max_tokens.
@pytest.mark.parametrize(
    "body,compatibility",
    [
        ({"max_tokens": 777}, USAGE_FLAG),
        ({"temperature": 0.2}, OWN_CAP),
        (None, OWN_CAP),
        (
            {"max_tokens": 777},
            {**USAGE_FLAG, "maxTokensField": "max_completion_tokens"},
        ),
        ({"max_tokens": 777}, {**OWN_CAP, "supportsStore": True}),
    ],
)
def test_req_06_check_refuses_a_cap_flag_out_of_place(body, compatibility):
    config = runtime_settings(body, compatibility)
    if body is None:
        del config["providers"]["keeplane"]["models"]["coder"]["body"]
    with pytest.raises(ValueError, match="streamed-usage flag"):
        opencode_adapter.check_settings(config, "http://127.0.0.1:41234/v1")


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        "temperature",
        {"baseURL": "https://api.openai.com/v1"},
        {"apiKey": "x"},
        {"seed": 1},
        {"temperature": 5},
        {"model": "gpt-5"},
        {"messages": []},
        {"stream": False},
        {"stream_options": {"include_usage": False}},
        {"max_completion_tokens": 777},
        {"max_tokens": 777, "max_completion_tokens": 32000},
    ],
)
def test_req_06_check_refuses_any_other_body(body):
    with pytest.raises(ValueError, match="reviewed request settings"):
        opencode_adapter.check_settings(
            runtime_settings(body), "http://127.0.0.1:41234/v1"
        )


# REQ-07 `keeplane code` with a refused setting prints the message, exits 1
# and starts no runtime; with valid settings the runtime gets them.
def test_req_07_keeplane_code_refuses_before_the_runtime(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
):
    settings_file.set_request_settings(
        "coder", {"baseURL": "https://api.openai.com/v1"}
    )
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert runtime[1] == []
    error = capsys.readouterr().err
    assert '"coder"' in error and '"baseURL", an address setting' in error
    assert "settings.json" in error


def test_req_07_keeplane_code_passes_the_settings(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    settings_file.set_request_settings("coder", SETTINGS)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    config = json.loads(runtime[1][0][1]["env"]["OPENCODE_CONFIG_CONTENT"])
    assert model_entry(config)["body"] == SETTINGS
