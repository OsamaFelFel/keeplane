"""Synthetic OpenAI-compatible responses; no tool is executed."""

import json


def send_protocol_response(handler, body):
    messages = body.get("messages", [])
    tool_call = {
        "id": "call_fixture",
        "type": "function",
        "function": {"name": "lookup", "arguments": '{"name":"sample"}'},
    }
    assistant = next(
        (
            index
            for index, row in enumerate(messages)
            if row.get("role") == "assistant" and row.get("tool_calls") == [tool_call]
        ),
        None,
    )
    tool_result = assistant is not None and any(
        row.get("role") == "tool"
        and row.get("tool_call_id") == "call_fixture"
        and row.get("content") == "synthetic lookup result"
        for row in messages[assistant + 1 :]
    )
    if body.get("stream"):
        if body.get("tools"):
            deltas = [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_fixture",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"name":'},
                        }
                    ],
                },
                {"tool_calls": [{"index": 0, "function": {"arguments": '"sample"}'}}]},
            ]
            finish = "tool_calls"
        else:
            deltas = [
                {"role": "assistant", "content": "synthetic "},
                {"content": "stream"},
            ]
            finish = "stop"
        chunks = [
            "data: "
            + json.dumps(
                {
                    "id": "fixture",
                    "object": "chat.completion.chunk",
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
            )
            + "\n\n"
            for delta in deltas
        ]
        chunks.append(
            "data: "
            + json.dumps(
                {
                    "id": "fixture",
                    "object": "chat.completion.chunk",
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                }
            )
            + "\n\n"
        )
        chunks.append("data: [DONE]\n\n")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header(
            "Content-Length", str(sum(len(chunk.encode()) for chunk in chunks))
        )
        handler.end_headers()
        for chunk in chunks:
            handler.wfile.write(chunk.encode())
            handler.wfile.flush()
    else:
        message = {
            "role": "assistant",
            "content": "synthetic tool-result answer" if tool_result else "OK",
        }
        if body.get("tools"):
            message.update({"content": None, "tool_calls": [tool_call]})
        data = json.dumps(
            {
                "id": "fixture",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if body.get("tools") else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    return tool_result
