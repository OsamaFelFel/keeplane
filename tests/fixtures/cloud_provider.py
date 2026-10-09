"""Authenticated OpenAI/Anthropic fixture for the protected Docker trial.

This is a test endpoint, not a production provider adapter. It records only
call counts and never prints or returns a provider key.
"""

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock


KEY_FILE = Path(os.environ["TRIAL_KEY_FILE"])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    count = 0
    lock = Lock()

    def reply(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"status": "ready"})
        if self.path == "/calls":
            with self.lock:
                return self.reply(200, {"count": type(self).count})
        return self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/v1/messages"):
            return self.reply(404, {"error": "Not found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 65536:
                return self.reply(400, {"error": "Invalid request size"})
            body = json.loads(self.rfile.read(size))
            expected = KEY_FILE.read_text().strip()
        except (ValueError, OSError):
            return self.reply(503, {"error": "Fixture unavailable"})
        bearer = hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + expected)
        anthropic = hmac.compare_digest(self.headers.get("x-api-key", ""), expected)
        if not (bearer or anthropic):
            return self.reply(401, {"error": "Provider key refused"})
        model = body.get("model", "mock-cloud")
        with self.lock:
            type(self).count += 1
        if self.path == "/v1/messages":
            return self.reply(200, {"id": "msg_cloud_fixture", "type": "message", "role": "assistant",
                                    "model": model,
                                    "content": [{"type": "text", "text": "mock cloud answer"}],
                                    "stop_reason": "end_turn", "stop_sequence": None,
                                    "usage": {"input_tokens": 2, "output_tokens": 3}})
        return self.reply(200, {"id": "cloud-fixture", "object": "chat.completion", "model": model,
                                "choices": [{"index": 0, "message": {
                                    "role": "assistant", "content": "mock cloud answer"},
                                    "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 2, "completion_tokens": 3,
                                          "total_tokens": 5}})

    def log_message(self, _format, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 18082), Handler).serve_forever()
