"""Deterministic host-side OpenAI-compatible runner for project-class journeys.

A test fixture only: it serves a fixed set of upstream model IDs, records every
completion it receives by upstream model, and can make chosen models fail with
503 to stand in for a provider that is down. Standard library only; it sends no
outbound requests.
"""

import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ClassRunner:
    def __init__(self, models, host="0.0.0.0", port=14424):
        self.models = list(models)
        self.calls = Counter()
        self.down = set()
        self.lock = threading.Lock()
        runner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/health":
                    self.reply(200, {"status": "ok"})
                elif self.path == "/v1/models":
                    self.reply(
                        200,
                        {
                            "object": "list",
                            "data": [
                                {"id": name, "object": "model"}
                                for name in runner.models
                            ],
                        },
                    )
                else:
                    self.reply(404, {"error": "unknown path"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                try:
                    request = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    self.reply(400, {"error": "invalid JSON"})
                    return
                if self.path != "/v1/chat/completions" or not isinstance(request, dict):
                    self.reply(404, {"error": "unknown path"})
                    return
                model = request.get("model")
                with runner.lock:
                    runner.calls[model] += 1
                    down = model in runner.down
                if down or model not in runner.models:
                    self.reply(503, {"error": "fixture model is down"})
                    return
                self.reply(
                    200,
                    {
                        "id": "class-runner-1",
                        "object": "chat.completion",
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "class answer",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 2,
                            "completion_tokens": 2,
                            "total_tokens": 4,
                        },
                    },
                )

            def reply(self, status, data):
                payload = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def snapshot(self):
        with self.lock:
            return Counter(self.calls)

    def set_down(self, models):
        with self.lock:
            self.down = set(models)
