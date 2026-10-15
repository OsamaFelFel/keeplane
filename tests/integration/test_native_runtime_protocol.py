"""Synthetic streaming/tool protocols keep current Django authorization."""

import json

import pytest

from tests.integration.test_native_runtime_authorization import gateway_config
from tests.support.native_runtime_trial import native_runtime_trial


def protocol_config(existing, admin):
    value = gateway_config(existing, admin)
    value["frontendPolicies"] = {"accessLog": {"database": {"llm": "metadata"}}}
    return value


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
@pytest.mark.parametrize("kind", ["stream", "tool", "stream-tool"])
def test_native_protocol_and_next_request_withdrawal(
    tmp_path, report_file, existing, kind
):
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        }
    ]
    body = {
        "model": "private",
        "messages": [{"role": "user", "content": "synthetic protocol prompt"}],
    }
    if kind != "tool":
        body["stream"] = True
    if kind != "stream":
        body["tools"] = tools
    expected_call = {
        "id": "call_fixture",
        "type": "function",
        "function": {"name": "lookup", "arguments": '{"name":"sample"}'},
    }
    with native_runtime_trial(
        tmp_path, existing, protocol_config, protocol=True
    ) as trial:
        response = trial.probe({"body": body, "observe_protocol": True})
        assert response["status"] == 200
        if kind != "tool":
            assert response["content_type"].startswith("text/event-stream")
            events = [
                line[6:]
                for line in response["body"].splitlines()
                if line.startswith("data: ")
            ]
            assert events[-1] == "[DONE]"
            chunks = [json.loads(event) for event in events[:-1]]
            choices = [
                choice for chunk in chunks for choice in chunk.get("choices", [])
            ]
            deltas = [choice.get("delta", {}) for choice in choices]
            if kind == "stream":
                assert (
                    "".join(delta.get("content", "") for delta in deltas)
                    == "synthetic stream"
                )
                assert choices[-1]["finish_reason"] == "stop"
            else:
                fragments = [
                    call for delta in deltas for call in delta.get("tool_calls", [])
                ]
                assert all(call["index"] == 0 for call in fragments)
                assert [call["id"] for call in fragments if "id" in call] == [
                    "call_fixture"
                ]
                assert [
                    call["function"]["name"]
                    for call in fragments
                    if "name" in call.get("function", {})
                ] == ["lookup"]
                assert (
                    "".join(
                        call.get("function", {}).get("arguments", "")
                        for call in fragments
                    )
                    == '{"name":"sample"}'
                )
                assert choices[-1]["finish_reason"] == "tool_calls"
        else:
            assert response["content_type"].startswith("application/json")
            message = json.loads(response["body"])["choices"][0]["message"]
            assert message["tool_calls"] == [expected_call]
        if kind != "stream":
            body = {
                "model": "private",
                "messages": [
                    {"role": "user", "content": "synthetic protocol prompt"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [expected_call],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_fixture",
                        "content": "synthetic lookup result",
                    },
                ],
            }
            result = trial.probe({"body": body, "observe_protocol": True})
            assert result["status"] == 200
            assert (
                json.loads(result["body"])["choices"][0]["message"]["content"]
                == "synthetic tool-result answer"
            )
        observed = trial.call("summary")
        count = 1 if kind == "stream" else 2
        assert observed["calls"] == ["mock-private"] * count
        assert observed["provider_key_used"] == [True] * count
        assert observed["developer_key_forwarded"] == [False] * count
        assert observed["tool_result_seen"] == (
            [False] if kind == "stream" else [False, True]
        )
        assert (
            observed["credential_headers"]
            == [
                {
                    "Authorization": True,
                    "X-Keeplane-Gateway-Credential": False,
                    "X-Keeplane-Project-ID": False,
                }
            ]
            * count
        )
        assert [row["model_id"] for row in observed["decisions"]] == ["private"] * (
            2 * count
        )
        assert all(
            row["keys"] == ["model_id", "project_id"] for row in observed["decisions"]
        )
        trial.call("withdraw")
        trial.call("reset")
        assert trial.probe({"body": body}) == 403
        assert not trial.call("summary")["calls"]
        assert trial.call("config") == trial.before
        assert (
            trial.before["existing_preserved"]
            and trial.before["existing_listed"] is existing
        )
        report_file.write_text(
            json.dumps(
                {
                    "existing": existing,
                    "kind": kind,
                    "content_preserved": True,
                    "server_key_only": True,
                    "next_request_withdrawal_no_contact": True,
                },
                indent=2,
            )
            + "\n"
        )
