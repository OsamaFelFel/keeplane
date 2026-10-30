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


SETTINGS = {
    "temperature": 0.37,
    "top_p": 0.81,
    "max_tokens": 123,
    "stop": ["END"],
    "seed": 7,
    "presence_penalty": 0.25,
    "frequency_penalty": -0.5,
    "user": "synthetic-settings-check",
}


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
@pytest.mark.parametrize("kind", ["json", "stream", "tool"])
def test_request_settings_reach_the_model_unchanged(
    tmp_path, report_file, existing, kind
):
    """Spec 004 ST26: settings the client sends arrive with the same values."""
    body = {
        "model": "private",
        "messages": [{"role": "user", "content": "synthetic settings prompt"}],
        **SETTINGS,
    }
    if kind == "stream":
        body["stream"] = True
    if kind == "tool":
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = False
    sent = {
        name: value
        for name, value in body.items()
        if name not in ("model", "messages", "tools")
    }
    with native_runtime_trial(
        tmp_path, existing, protocol_config, protocol=True
    ) as trial:
        response = trial.probe({"body": body, "observe_protocol": True})
        assert response["status"] == 200 and not response["incomplete"]
        observed = trial.call("summary")
        assert observed["calls"] == ["mock-private"]
        received = observed["settings"][0]
        # Setting names and values only; no prompt, answer or credential.
        report_file.write_text(
            json.dumps(
                {
                    "existing": existing,
                    "kind": kind,
                    "changed": sorted(
                        name
                        for name in sent
                        if received["values"].get(name) != sent[name]
                    ),
                    "added_by_gateway": received["other_fields"],
                },
                indent=2,
            )
            + "\n"
        )
        assert received["values"] == sent
        assert trial.call("config") == trial.before


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
@pytest.mark.parametrize("failure", ["before", "mid"])
def test_a_failed_stream_is_visible_and_reaches_no_other_model(
    tmp_path, report_file, existing, failure
):
    """A provider failure is not shown as a finished answer or sent elsewhere.

    No fallback is configured on this gateway path, so only the chosen model is
    contacted; after recovery the next request is checked and answered again.
    """
    body = {
        "model": "private",
        "messages": [{"role": "user", "content": "synthetic failure prompt"}],
        "stream": True,
    }
    with native_runtime_trial(
        tmp_path, existing, protocol_config, protocol=True
    ) as trial:
        trial.call("protocol_failure", failure)
        response = trial.probe({"body": body, "observe_protocol": True})
        if isinstance(response, int):
            status, incomplete, finished = response, None, False
        else:
            events = [
                line[6:]
                for line in response["body"].splitlines()
                if line.startswith("data: ")
            ]
            status, incomplete = response["status"], response["incomplete"]
            finished = (
                status == 200 and not incomplete and bool(events)
                and events[-1] == "[DONE]"
            )
        observed = trial.call("summary")
        report_file.write_text(
            json.dumps(
                {
                    "existing": existing,
                    "failure": failure,
                    "status": status,
                    "incomplete": incomplete,
                    "reported_as_finished": finished,
                    "providers_contacted": observed["calls"],
                },
                indent=2,
            )
            + "\n"
        )
        if failure == "before":
            assert status >= 500
        assert not finished
        assert observed["calls"] == ["mock-private"]
        trial.call("reset")
        recovered = trial.probe({"body": body, "observe_protocol": True})
        assert recovered["status"] == 200 and not recovered["incomplete"]
        assert trial.call("summary")["calls"] == ["mock-private"]
        assert trial.call("config") == trial.before
