"""Synthetic tool replies; caller must first verify actual provider authentication."""

import hashlib
import json
from pathlib import Path

RULE = "INSTALLED_CLI_RULE: preserve the addition function's interface."
TEXT = RULE + "\nPRIVATE_MIGRATION_INSTRUCTION\n"
DIGEST = hashlib.sha256(TEXT.encode()).hexdigest()
PHASES = ("first", "replace", "resume")


def text(content):
    if isinstance(content, str):
        return content
    return "".join(
        block["text"] for block in content or [] if block.get("type") == "text"
    )


def records(messages, protocol):
    calls, results = {}, set()
    for row in messages:
        if protocol == "openai":
            for call in row.get("tool_calls", []):
                value = call["function"]
                calls[call["id"]] = (value["name"], json.loads(value["arguments"]))
            if row.get("role") == "tool" and row.get("content"):
                results.add(row["tool_call_id"])
        else:
            for block in (
                row.get("content", []) if isinstance(row.get("content"), list) else []
            ):
                if row.get("role") == "assistant" and block.get("type") == "tool_use":
                    calls[block["id"]] = (block["name"], block["input"])
                if row.get("role") == "user" and block.get("type") == "tool_result":
                    assert not block.get("is_error") and block.get("content")
                    results.add(block["tool_use_id"])
    return calls, results


def prepare(body, protocol, owner_label, *, target=Path("/client/project/math.py")):
    """Return an exact synthetic tool response without performing tool execution."""
    assert protocol in {"openai", "anthropic"} and owner_label in {"a", "a_next", "b"}
    assert body["model"] == "fixture-personal"
    tools = {
        tool["function"]["name"] if protocol == "openai" else tool["name"]
        for tool in body["tools"]
    }
    assert {"read", "edit"} <= tools
    messages = body["messages"]
    latest = max(
        index
        for index, row in enumerate(messages)
        if row["role"] == "user" and "PERSONAL_TURN:" in text(row.get("content"))
    )
    prompt = text(messages[latest]["content"])
    phases = [phase for phase in PHASES if "PERSONAL_TURN:" + phase in prompt]
    assert len(phases) == 1
    phase = phases[0]
    actor = "a" if owner_label == "a_next" else owner_label
    prefix = f"personal_{protocol}_{actor}_"
    system = (
        body.get("system")
        if protocol == "anthropic"
        else [row for row in messages if row["role"] == "system"]
    )
    assert json.dumps(f"SHA-256 {DIGEST})\n{TEXT}")[1:-1] in json.dumps(system)
    prior_calls, prior_results = records(messages[:latest], protocol)
    for prior in PHASES[: PHASES.index(phase)]:
        for index, name in enumerate(("read", "edit")):
            identifier = prefix + prior + "_" + str(index)
            assert identifier in prior_results and identifier in prior_calls
            expected = {"path": str(target)}
            if name == "edit":
                expected.update(oldString="return a - b", newString="return a + b")
            assert prior_calls[identifier] == (name, expected)
    calls, results = records(messages[latest + 1 :], protocol)
    identifiers = [prefix + phase + "_" + str(index) for index in range(2)]
    completed = sum(identifier in results for identifier in identifiers)
    assert set(calls) <= set(identifiers) and results <= set(calls)
    assert results == set(identifiers[:completed])
    for index, identifier in enumerate(identifiers):
        if identifier not in calls:
            continue
        expected = {"path": str(target)}
        if index:
            expected.update(oldString="return a - b", newString="return a + b")
        assert calls[identifier] == (("read", "edit")[index], expected)
    arguments = {"path": str(target)}
    name = "read" if completed == 0 else "edit"
    if name == "edit":
        arguments.update(oldString="return a - b", newString="return a + b")
    identifier = identifiers[completed] if completed < 2 else None
    if protocol == "openai":
        message = {"role": "assistant", "content": "The addition function is fixed."}
        if identifier:
            message.update(
                content=None,
                tool_calls=[
                    {
                        "id": identifier,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            )
        choice = {
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if identifier else "stop",
        }
        if body.get("stream"):
            choice["delta"] = choice.pop("message")
        response = {
            "id": "personal-fixture",
            "model": "fixture-personal",
            "object": "chat.completion.chunk"
            if body.get("stream")
            else "chat.completion",
            "choices": [choice],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        raw = json.dumps(response).encode()
        if body.get("stream"):
            raw = b"data: " + raw + b"\n\ndata: [DONE]\n\n"
    else:
        content = (
            {"type": "tool_use", "id": identifier, "name": name, "input": arguments}
            if identifier
            else {"type": "text", "text": "The addition function is fixed."}
        )
        stop = "tool_use" if identifier else "end_turn"
        response = {
            "id": "msg_personal",
            "type": "message",
            "role": "assistant",
            "model": "fixture-personal",
            "content": [content],
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        raw = json.dumps(response).encode()
        if body.get("stream"):
            start = dict(response, content=[], stop_reason=None)
            block = dict(content, input={}) if identifier else dict(content, text="")
            delta = (
                {"type": "input_json_delta", "partial_json": json.dumps(arguments)}
                if identifier
                else {"type": "text_delta", "text": content["text"]}
            )
            events = [
                {"type": "message_start", "message": start},
                {"type": "content_block_start", "index": 0, "content_block": block},
                {"type": "content_block_delta", "index": 0, "delta": delta},
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop, "stop_sequence": None},
                    "usage": {"output_tokens": 5},
                },
                {"type": "message_stop"},
            ]
            raw = b"".join(
                (
                    "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
                ).encode()
                for event in events
            )
    return raw, {
        "protocol": protocol,
        "owner_label": owner_label,
        "phase": phase,
        "tool": name if identifier else None,
        "history_checked": phase != "first",
    }
