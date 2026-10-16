"""Host-only response/history controls, not a native provider-transport proof."""

import copy
import json

import pytest

from tests.fixtures.personal_cli_tools import DIGEST, TEXT, prepare


def body(protocol, stream):
    system = f"Repository instruction: AGENTS.md (SHA-256 {DIGEST})\n{TEXT}"
    request = {
        "model": "fixture-personal",
        "stream": stream,
        "messages": [{"role": "user", "content": "PERSONAL_TURN:first"}],
    }
    if protocol == "openai":
        request["messages"].insert(0, {"role": "system", "content": system})
        request["tools"] = [
            {"type": "function", "function": {"name": name}}
            for name in ("read", "edit")
        ]
    else:
        request["system"] = [{"type": "text", "text": system}]
        request["tools"] = [{"name": name} for name in ("read", "edit")]
    return request


def pair(protocol, phase, index):
    identifier = f"personal_{protocol}_a_{phase}_{index}"
    name = ("read", "edit")[index]
    arguments = {"path": "/client/project/math.py"}
    if index:
        arguments.update(oldString="return a - b", newString="return a + b")
    if protocol == "openai":
        return [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": identifier,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": identifier, "content": "ok"},
        ]
    return [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": identifier, "name": name, "input": arguments}
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": identifier, "content": "ok"}
            ],
        },
    ]


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("stream", [False, True])
def test_actual_protocol_records_survive_fresh_replacement_turn(protocol, stream):
    request = body(protocol, stream)
    for phase, owner in (("first", "a"), ("replace", "a_next"), ("resume", "a_next")):
        if phase != "first":
            request["messages"].append(
                {"role": "user", "content": "PERSONAL_TURN:" + phase}
            )
        for index, tool in enumerate(("read", "edit")):
            raw, observed = prepare(request, protocol, owner)
            assert observed["tool"] == tool and observed["phase"] == phase
            assert observed["history_checked"] == (phase != "first")
            if stream:
                assert b"data: " in raw
                assert (b"input_json_delta" in raw) == (protocol == "anthropic")
            elif protocol == "anthropic":
                assert json.loads(raw)["content"][0]["type"] == "tool_use"
            request["messages"].extend(pair(protocol, phase, index))
        raw, observed = prepare(request, protocol, owner)
        assert observed["tool"] is None
        assert b"The addition function is fixed." in raw


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "fault", ["missing-result", "changed-arguments", "changed-instructions"]
)
def test_refuse_incomplete_or_changed_resumed_history(protocol, fault):
    request = body(protocol, True)
    request["messages"].extend(pair(protocol, "first", 0) + pair(protocol, "first", 1))
    request["messages"].append({"role": "user", "content": "PERSONAL_TURN:replace"})
    if fault == "missing-result":
        del request["messages"][-2]
    elif fault == "changed-arguments":
        call = request["messages"][-3]
        if protocol == "openai":
            call["tool_calls"][0]["function"]["arguments"] = '{"path":"wrong"}'
        else:
            call["content"][0]["input"] = {"path": "wrong"}
    elif protocol == "openai":
        request["messages"][0]["content"] += "changed"
        request["messages"][0]["content"] = request["messages"][0]["content"].replace(
            TEXT, "wrong"
        )
    else:
        request["system"][0]["text"] = request["system"][0]["text"].replace(
            TEXT, "wrong"
        )
    with pytest.raises(AssertionError):
        prepare(copy.deepcopy(request), protocol, "a_next")
