"""Protected loopback fixture for a real, offline runtime read/edit turn."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json


class Handler(BaseHTTPRequestHandler):
    calls = []
    grant = "synthetic-cli-grant"
    target = None
    required_instruction = None
    instruction_checks = 0
    instruction_children = 0
    forbidden_instruction = None
    turn_scoped = False
    call_prefix = "call_"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer " + self.grant:
            self.send_error(401)
            return
        if self.path != "/v1/chat/completions" or body.get("model") != "fixture-coder":
            self.send_error(403)
            return
        tools = {tool["function"]["name"] for tool in body.get("tools", [])}
        child = bool(self.headers.get("x-opencode-parent-session-id"))
        if tools and self.required_instruction:
            rule, digest = self.required_instruction
            system = json.dumps([row for row in body["messages"] if row.get("role") == "system"])
            assert rule in system and digest in system
            assert f"SHA-256 {digest})\\n{rule}" in system
            assert "NESTED_INSTRUCTION_MUST_NOT_APPLY" not in json.dumps(body)
            assert not self.forbidden_instruction or self.forbidden_instruction not in json.dumps(body)
            type(self).instruction_checks += 1
            type(self).instruction_children += int(child)
        messages = body["messages"]
        if self.turn_scoped:
            last_user = max(index for index, message in enumerate(messages) if message.get("role") == "user")
            messages = messages[last_user:]
        completed = sum(message.get("role") == "tool" for message in messages)
        message = {"role": "assistant", "content": "The addition function is fixed."}
        finish = "stop"
        if tools and completed < (1 if child else 2):
            name = "read" if completed == 0 else "edit"
            arguments = {"path": str(self.target)}
            if completed:
                arguments.update(oldString="return a - b", newString="return a + b")
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": self.call_prefix + str(completed), "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }]}
            finish = "tool_calls"
            self.calls.append(name)
        elif tools and self.required_instruction and not child and completed == 2:
            arguments = {"agent": "explore", "description": "Check the addition file",
                         "prompt": "Read " + str(self.target) + " and acknowledge without edits.", "background": False}
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_child", "type": "function",
                "function": {"name": "subagent", "arguments": json.dumps(arguments)},
            }]}
            finish = "tool_calls"
            self.calls.append("subagent")
        choice = {"index": 0, "message": message, "finish_reason": finish}
        if body.get("stream"):
            choice = {"index": 0, "delta": message, "finish_reason": finish}
        response = {"id": "cli-fixture", "object": "chat.completion.chunk" if body.get("stream") else "chat.completion",
                    "model": "fixture-coder", "choices": [choice],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        payload = json.dumps(response).encode()
        if body.get("stream"):
            payload = b"data: " + payload + b"\n\ndata: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if body.get("stream") else "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start(target, required_instruction=None, *, handler=Handler, turn_scoped=False):
    Handler.target = target
    Handler.calls = []
    Handler.required_instruction = required_instruction
    Handler.instruction_checks = 0
    Handler.instruction_children = 0
    Handler.forbidden_instruction = None
    Handler.turn_scoped = turn_scoped
    Handler.call_prefix = "call_"
    return ThreadingHTTPServer(("127.0.0.1", 0), handler)
