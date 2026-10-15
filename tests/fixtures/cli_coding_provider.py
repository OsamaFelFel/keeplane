"""Protected loopback fixture for a real, offline runtime read/edit turn."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json


class Handler(BaseHTTPRequestHandler):
    calls = []
    grant = "synthetic-cli-grant"
    target = None

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
        completed = sum(message.get("role") == "tool" for message in body["messages"])
        message = {"role": "assistant", "content": "The addition function is fixed."}
        finish = "stop"
        if tools and completed < 2:
            name = "read" if completed == 0 else "edit"
            arguments = {"path": str(self.target)}
            if completed:
                arguments.update(oldString="return a - b", newString="return a + b")
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_" + str(completed), "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }]}
            finish = "tool_calls"
            self.calls.append(name)
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


def start(target):
    Handler.target = target
    Handler.calls = []
    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
