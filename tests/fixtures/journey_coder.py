"""Deterministic, tool-capable local runner for the developer journey (task 009-13).

A test fixture only. It listens where the preview allows a host runner
(``host.docker.internal:14424``), so an admin can add it as a local model. A
turn that offers tools gets the same two tool calls every time: read the
sample repo's file, then edit ``return a - b`` to ``return a + b``. After the
tool results it answers with a fixed sentence. Every answer reports the same
token usage, so the journey can check the totals exactly. It also keeps the
request settings (Spec 004 ST26) each request carried, as received, and the
names of any of Keeplane's own headers that reached it. Standard library
only; it sends no outbound requests.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = "The addition function is fixed."
OLD, NEW = "return a - b", "return a + b"
# Per answer, whatever was asked.
USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
# The request settings kept from each request, by the name they arrived under.
SETTINGS = ("temperature", "top_p", "max_tokens", "max_completion_tokens")
# Keeplane's own headers, which a gateway must never pass on to a model.
KEEPLANE_HEADERS = (
    "authorization",
    "x-keeplane-gateway-credential",
    "x-keeplane-project-id",
    "x-keeplane-developer-route",
    "x-keeplane-installed-runtime",
)


class JourneyCoder:
    def __init__(self, models, host="0.0.0.0", port=14424):
        self.models = list(models)
        self.target = None  # The file this turn edits; set before each turn.
        self.answers = 0  # Answers served, each with USAGE.
        self.tools = []  # Tool calls sent, in order.
        self.received = []  # Each request's SETTINGS, in order.
        self.forwarded = []  # Each request's KEEPLANE_HEADERS, by name only.
        self.lock = threading.Lock()
        coder = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/health":
                    self.reply(200, {"status": "ok"})
                elif self.path == "/v1/models":
                    data = [{"id": name, "object": "model"} for name in coder.models]
                    self.reply(200, {"object": "list", "data": data})
                else:
                    self.reply(404, {"error": "unknown path"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                try:
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    self.reply(400, {"error": "invalid JSON"})
                    return
                if (
                    self.path != "/v1/chat/completions"
                    or not isinstance(body, dict)
                    or body.get("model") not in coder.models
                ):
                    self.reply(404, {"error": "unknown model or path"})
                    return
                sent = {name.lower() for name in self.headers}
                with coder.lock:
                    coder.received.append({name: body.get(name) for name in SETTINGS})
                    coder.forwarded.append(
                        [name for name in KEEPLANE_HEADERS if name in sent]
                    )
                message, finish = coder.next_message(body)
                streamed = bool(body.get("stream"))
                wants_usage = (body.get("stream_options") or {}).get(
                    "include_usage"
                ) is True
                with coder.lock:
                    coder.answers += 1
                head = {"id": "journey-coder", "model": body["model"]}
                if not streamed:
                    self.reply(
                        200,
                        {
                            **head,
                            "object": "chat.completion",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": message,
                                    "finish_reason": finish,
                                }
                            ],
                            "usage": USAGE,
                        },
                    )
                    return
                chunk = {
                    **head,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {"index": 0, "delta": message, "finish_reason": finish}
                    ],
                }
                payload = b"data: " + json.dumps(chunk).encode() + b"\n\n"
                if wants_usage:
                    last = {
                        **head,
                        "object": "chat.completion.chunk",
                        "choices": [],
                        "usage": USAGE,
                    }
                    payload += b"data: " + json.dumps(last).encode() + b"\n\n"
                payload += b"data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def reply(self, status, data):
                payload = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def next_message(self, body):
        """Read, then edit, then answer: counted from this turn's tool results."""
        tools = {
            (tool.get("function") or {}).get("name")
            for tool in body.get("tools") or []
            if isinstance(tool, dict)
        }
        messages = body.get("messages") or []
        users = [i for i, row in enumerate(messages) if row.get("role") == "user"]
        turn = messages[users[-1] :] if users else messages
        done = sum(row.get("role") == "tool" for row in turn)
        if not {"read", "edit"} <= tools or done >= 2 or self.target is None:
            return {"role": "assistant", "content": ANSWER}, "stop"
        name = "read" if done == 0 else "edit"
        arguments = {"path": str(self.target)}
        if done:
            arguments.update(oldString=OLD, newString=NEW)
        with self.lock:
            self.tools.append(name)
        call = {
            "id": f"call_{len(self.tools)}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [call],
        }, "tool_calls"

    def served(self):
        with self.lock:
            return self.answers

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
