"""The runtime settings `keeplane code` writes: API keys only, usage on.

Cases: tests/unit/cli-runtime-settings-cases.md (KEY-01 to KEY-08).
"""

import copy
import functools
import json
import re
import subprocess
from pathlib import Path

import pytest

from components.cli import opencode_adapter

GATEWAY = "https://gateway.test/v1"
SIGN_IN_PLUGINS = (
    "opencode.provider.chatgpt",
    "opencode.provider.openai",
    "opencode.provider.github.copilot",
    "opencode.provider.gitlab",
)


def launch(tmp_path, monkeypatch, *, instructions=(), account_context=None):
    """Run one stand-in turn; return the settings and environment the runtime got."""
    seen = {}

    def version(command, **options):
        return subprocess.CompletedProcess(command, 0, "opencode v2.0.27\n", "")

    def turn(command, **options):
        seen["command"], seen["env"] = command, options["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    binary = tmp_path / "runtime"
    binary.touch()
    directory = tmp_path / "repository"
    directory.mkdir(exist_ok=True)
    for name in instructions:
        (directory / name).write_text("Use tabs.\n")
    monkeypatch.setattr(opencode_adapter.subprocess, "run", version)
    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)
    opencode_adapter.run(
        str(binary),
        str(directory),
        GATEWAY,
        "coder",
        "Fix it.",
        "synthetic-grant",
        instructions=[directory / name for name in instructions],
        account_context=account_context,
    )
    return json.loads(seen["env"]["OPENCODE_CONFIG_CONTENT"]), seen


# KEY-01 Only the gateway, with API keys: one provider, the built-in
# OpenAI-compatible package, the gateway address and the grant from the
# environment; every other provider is denied by policy.
PROJECT = "7f8e4c1a-1b2c-4d3e-8f90-123456789abc"
ACTOR = "0b6f3a52-8d9e-4f1a-9c2b-3d4e5f6a7b8c"


@pytest.mark.parametrize(
    "context",
    [
        None,
        {"issuer": "https://keeplane.test", "actor_id": ACTOR, "project_id": PROJECT},
    ],
)
def test_key_01_only_the_gateway_provider(tmp_path, monkeypatch, context):
    config, seen = launch(tmp_path, monkeypatch, account_context=context)
    assert list(config["providers"]) == ["keeplane"]
    provider = config["providers"]["keeplane"]
    assert provider["package"] == "@opencode/ai/providers/openai-compatible"
    assert provider["env"] == ["KEEPLANE_RUNTIME_GRANT"]
    assert provider["settings"] == {"baseURL": GATEWAY}
    assert config["model"] == "keeplane/coder"
    assert seen["command"][-2:] == ["--model", "keeplane/coder"]
    assert config["experimental"] == {
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": "keeplane", "effect": "allow"},
        ]
    }
    if context:
        assert provider["headers"] == {"X-Keeplane-Project-ID": PROJECT}
    else:
        assert "headers" not in provider
    assert "synthetic-grant" not in json.dumps(config)


# KEY-02 No provider sign-in: every built-in provider plugin (ChatGPT, OpenAI,
# Copilot, GitLab sign-ins and local-runner discovery) is turned off, web
# tools stay off, and no settings key names a sign-in, key or credential.
@pytest.mark.parametrize("instructions", [(), ("AGENTS.md",)])
def test_key_02_no_provider_sign_in(tmp_path, monkeypatch, instructions):
    config, _ = launch(tmp_path, monkeypatch, instructions=instructions)
    directives = [row for row in config["plugins"] if isinstance(row, str)]
    assert directives == [
        "-opencode.tool.webfetch",
        "-opencode.tool.websearch",
        "-opencode.websearch.*",
        "-opencode.provider.*",
    ]
    assert config["websearch"] is False
    packages = [row["package"] for row in config["plugins"] if not isinstance(row, str)]
    expected = [
        str(Path(opencode_adapter.__file__).with_name("instruction_plugin").resolve())
    ]
    assert packages == (expected if instructions else [])
    text = json.dumps(config).lower()
    for word in (
        "oauth",
        "auth",
        "apikey",
        "api_key",
        "login",
        "subscription",
        "refresh",
    ):
        assert word not in text.replace("authorization", ""), word


# KEY-03 Usage on streamed answers: the gateway model asks for usage in its
# streamed answers (stream_options.include_usage).
def test_key_03_usage_on_streamed_answers(tmp_path, monkeypatch):
    config, _ = launch(tmp_path, monkeypatch)
    model = config["providers"]["keeplane"]["models"]["coder"]
    assert model == {
        "name": "coder",
        "compatibility": {"supportsUsageInStreaming": True},
    }


def good():
    return {
        "providers": {
            "keeplane": {
                "package": "@opencode/ai/providers/openai-compatible",
                "env": ["KEEPLANE_RUNTIME_GRANT"],
                "settings": {"baseURL": GATEWAY},
                "models": {
                    "coder": {
                        "name": "coder",
                        "compatibility": {"supportsUsageInStreaming": True},
                    }
                },
                "headers": {"X-Keeplane-Project-ID": "p1"},
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


def changed(edit):
    config = good()
    edit(config)
    return config


def provider(config):
    return config["providers"]["keeplane"]


def model(config):
    return provider(config)["models"]["coder"]


def enable(plugin, config):
    config["plugins"].append(plugin)


TAMPERED = {
    # Another provider next to the gateway, or in its place.
    "openai provider": lambda c: c["providers"].update(
        openai={"settings": {"apiKey": "k"}}
    ),
    "anthropic provider": lambda c: c["providers"].update(anthropic={}),
    "only anthropic": lambda c: c.update(providers={"anthropic": provider(c)}),
    "model from openai": lambda c: c.update(model="openai/gpt-5"),
    "model from anthropic": lambda c: c.update(model="anthropic/claude-sonnet"),
    # The gateway provider pointed elsewhere, or given a stored key or sign-in.
    "openai package": lambda c: provider(c).update(
        package="@opencode/ai/providers/openai"
    ),
    "anthropic package": lambda c: provider(c).update(
        package="@opencode/ai/providers/anthropic"
    ),
    "other address": lambda c: provider(c)["settings"].update(
        baseURL="https://api.openai.com/v1"
    ),
    "api key": lambda c: provider(c)["settings"].update(apiKey="sk-synthetic"),
    "provider key env": lambda c: provider(c)["env"].append("OPENAI_API_KEY"),
    "auth block": lambda c: provider(c).update(auth={"type": "oauth"}),
    "authorization header": lambda c: provider(c)["headers"].update(
        Authorization="Bearer x"
    ),
    "model address": lambda c: provider(c)["models"]["coder"].update(
        settings={"baseURL": "x"}
    ),
    "model package": lambda c: provider(c)["models"]["coder"].update(
        package="@opencode/ai/providers/anthropic"
    ),
    "model oauth": lambda c: provider(c)["models"]["coder"].update(oauth=True),
    "nested access token": lambda c: provider(c)["models"]["coder"].update(
        options={"accessToken": "x"}
    ),
    "subscription": lambda c: c["experimental"].update(subscription="chatgpt"),
    # A sign-in plugin turned back on, or the provider plugins left on.
    "provider plugins on": lambda c: c["plugins"].remove("-opencode.provider.*"),
    "web tools on": lambda c: c["plugins"].remove("-opencode.tool.webfetch"),
    "websearch on": lambda c: c.update(websearch=True),
    **{"enable " + name: functools.partial(enable, name) for name in SIGN_IN_PLUGINS},
    "enable every plugin": lambda c: c["plugins"].append("*"),
    "repo plugin": lambda c: c["plugins"].append({"package": "/repo/plugin"}),
    # The provider policy loosened or dropped.
    "allow openai": lambda c: c["experimental"]["policies"].append(
        {"action": "provider.use", "resource": "openai", "effect": "allow"}
    ),
    "no policy": lambda c: c.pop("experimental"),
    # An unreviewed settings key (MCP servers, sign-in settings, …).
    "mcp": lambda c: c.update(mcp={"remote": {"url": "https://example.invalid"}}),
    "auth key": lambda c: c.update(auth={"openai": {"type": "oauth"}}),
    "enabled providers": lambda c: c.update(enabled_providers=["openai"]),
    # Sharing or snapshots turned on, or a reviewed key left out.
    "share auto": lambda c: c.update(share="auto"),
    "share manual": lambda c: c.update(share="manual"),
    "snapshots on": lambda c: c.update(snapshots=True),
    "no snapshots key": lambda c: c.pop("snapshots"),
    "no websearch key": lambda c: c.pop("websearch"),
    # A model entry that is more, or less, than its name and the usage flag.
    "model provider package": lambda c: model(c).update(
        provider={"package": "@opencode/ai/providers/anthropic"}
    ),
    "model api url": lambda c: model(c).update(
        api={"url": "https://api.openai.com/v1"}
    ),
    "model options address": lambda c: model(c).update(
        options={"baseURL": "https://api.anthropic.com"}
    ),
    "model limit": lambda c: model(c).update(limit={"context": 1}),
    "empty compatibility": lambda c: model(c).update(compatibility={}),
    "usage off": lambda c: model(c).update(
        compatibility={"supportsUsageInStreaming": False}
    ),
    "extra compatibility": lambda c: model(c)["compatibility"].update(
        supportsStore=True
    ),
    "no compatibility": lambda c: model(c).pop("compatibility"),
    "other name": lambda c: model(c).update(name="gpt-5"),
    # Keeplane's instruction plugin given more than its options.
    "instruction plugin extra": lambda c: c["plugins"].insert(
        0, {"package": "/cli/instruction_plugin", "options": {}, "install": True}
    ),
}


# KEY-04 The runtime settings check passes what `keeplane code` writes.
def test_key_04_reviewed_settings_pass():
    opencode_adapter.check_settings(good(), GATEWAY)
    with_plugin = good()
    with_plugin["plugins"].insert(
        0, {"package": "/cli/instruction_plugin", "options": {}}
    )
    opencode_adapter.check_settings(with_plugin, GATEWAY, "/cli/instruction_plugin")


# KEY-05 No runtime sign-in, subscription or OAuth path for OpenAI or
# Anthropic (or any other provider) can be enabled through the settings:
# each change is refused before the runtime starts.
@pytest.mark.parametrize("name", sorted(TAMPERED))
def test_key_05_sign_in_paths_are_refused(name):
    config = changed(TAMPERED[name])
    assert config != good()
    # Keeplane's own plugin is allowed, so a refusal is about the change itself.
    plugin = "/cli/instruction_plugin" if name == "instruction plugin extra" else None
    with pytest.raises(ValueError):
        opencode_adapter.check_settings(copy.deepcopy(config), GATEWAY, plugin)


def test_key_05_refusal_stops_before_the_runtime(tmp_path, monkeypatch):
    started = []
    original = opencode_adapter.check_settings

    def tampered(config, gateway, plugin=None):
        config["providers"]["openai"] = {}
        return original(config, gateway, plugin)

    monkeypatch.setattr(opencode_adapter, "check_settings", tampered)
    monkeypatch.setattr(
        opencode_adapter.subprocess, "run", lambda *a, **k: started.append(a)
    )
    monkeypatch.setattr(
        opencode_adapter, "coding_turn", lambda *a, **k: started.append(a)
    )
    binary = tmp_path / "runtime"
    binary.touch()
    with pytest.raises(ValueError, match="only the Keeplane gateway"):
        opencode_adapter.run(
            str(binary), str(tmp_path), GATEWAY, "coder", "Fix.", "grant"
        )
    assert started == []


# KEY-06 Usage from a turn: input (cached input included), output (reasoning
# included), requests and requests without usage, from step_finish events.
def test_key_06_turn_usage():
    def step(**tokens):
        return json.dumps(
            {
                "type": "step_finish",
                "sessionID": "s",
                "part": {"type": "step-finish", "tokens": tokens},
            }
        )

    start = json.dumps({"type": "step_start", "part": {"type": "step-start"}})
    stdout = "\n".join(
        [
            json.dumps({"type": "text", "part": {"text": "hi"}}),
            start,
            step(input=100, output=20, reasoning=5, cache={"read": 30, "write": 2}),
            "not json",
            step(input=10, output=3, reasoning=0, cache={"read": 0, "write": 0}),
            step(input=0, output=0, reasoning=0, cache={"read": 0, "write": 0}),
            json.dumps({"type": "step_finish", "part": {}}),
        ]
    )
    assert opencode_adapter.turn_usage(stdout) == {
        "input_tokens": 142,
        "output_tokens": 28,
        "requests": 4,
        "requests_without_usage": 2,
    }
    # The runtime prints no step_finish for a turn's last step: that request
    # counts, without usage.
    last = "\n".join(
        [start, step(input=6, output=3, reasoning=2, cache={"read": 4}), start]
    )
    assert opencode_adapter.turn_usage(last) == {
        "input_tokens": 10,
        "output_tokens": 5,
        "requests": 2,
        "requests_without_usage": 1,
    }


# KEY-07 No model request in the turn, or nonsense counts: nothing to report,
# and negative, fractional, boolean or text counts count as zero.
def test_key_07_no_usage():
    assert opencode_adapter.turn_usage("") is None
    assert opencode_adapter.turn_usage(json.dumps({"type": "error"})) is None
    odd = json.dumps(
        {
            "type": "step_finish",
            "part": {
                "tokens": {
                    "input": -5,
                    "output": 1.5,
                    "reasoning": True,
                    "cache": {"read": "9"},
                }
            },
        }
    )
    assert opencode_adapter.turn_usage(odd) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "requests": 1,
        "requests_without_usage": 1,
    }


# KEY-08 The CLI has no command to sign in with a personal subscription:
# `login` signs in to Keeplane only, and no command or option names a
# provider sign-in.
def test_key_08_no_subscription_sign_in_command():
    source = (Path(opencode_adapter.__file__).with_name("keeplane.py")).read_text()
    commands = set(re.findall(r'add_parser\(\s*"([a-z-]+)"', source))
    assert "login" in commands
    for word in (
        "auth",
        "oauth",
        "subscription",
        "chatgpt",
        "claude",
        "anthropic",
        "openai",
        "copilot",
        "provider-login",
    ):
        assert not any(word in command for command in commands), word
    login = source.split('add_parser("login"', 1)[1].split("add_parser(", 1)[0]
    options = set(re.findall(r'add_argument\("(--[a-z-]+)"', login))
    assert options == {"--server", "--profile", "--timeout", "--device"}
