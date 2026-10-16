"""Owned shell barrier behind the actual protected native gateway."""

import json
from typing import ClassVar

from tests.fixtures.installed_cli_provider import InstalledCliProvider


class CancellationProvider(InstalledCliProvider):
    started: ClassVar[list[str]] = []
    interrupted_calls: ClassVar[dict[str, bool]] = {}
    recovered = 0

    def details(self):
        return {
            "started": self.started,
            "recovered": self.recovered,
            "interrupted_calls": self.interrupted_calls,
        }

    def respond(self, body):
        if not body.get("tools"):
            return False
        last = max(
            i for i, row in enumerate(body["messages"]) if row.get("role") == "user"
        )
        prompt = json.dumps(body["messages"][last])
        for label in ("SIGINT", "SIGTERM"):
            if "RECOVER_" + label in prompt:
                history = body["messages"][:last]
                assert "FIRST_SAVED_TURN" in json.dumps(history)
                calls = {
                    call["id"]: call["function"]["name"]
                    for row in history
                    for call in row.get("tool_calls", [])
                }
                results = {
                    row["tool_call_id"]
                    for row in history
                    if row.get("role") == "tool" and row.get("content")
                }
                completed = {"first_0", "first_1", "second_0", "second_1"}
                assert completed <= calls.keys() & results
                assert {calls[key] for key in completed} == {"read", "edit"}
                self.interrupted_calls[label] = calls.get("owned_" + label) == "shell"
                type(self).recovered += 1
                type(self).call_prefix = "recover_" + label + "_"
                return False
            if "CANCEL_" + label not in prompt:
                continue
            assert label not in self.started, "The owned tool must start once"
            assert "shell" in {tool["function"]["name"] for tool in body["tools"]}
            self.started.append(label)
            self.calls.append("shell")
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "owned_" + label,
                        "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": json.dumps(
                                {
                                    "command": "python3 owned-barrier.py " + label,
                                    "workdir": str(self.target.parent),
                                    "timeout": 60000,
                                    "background": False,
                                }
                            ),
                        },
                    }
                ],
            }
            choice = {"index": 0, "message": message, "finish_reason": "tool_calls"}
            if body.get("stream"):
                choice["delta"] = choice.pop("message")
            value = {
                "id": "cancel-fixture",
                "object": "chat.completion.chunk"
                if body.get("stream")
                else "chat.completion",
                "model": "fixture-coder",
                "choices": [choice],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
            payload = json.dumps(value).encode()
            if body.get("stream"):
                payload = b"data: " + payload + b"\n\ndata: [DONE]\n\n"
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/event-stream" if body.get("stream") else "application/json",
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return True
        return False
