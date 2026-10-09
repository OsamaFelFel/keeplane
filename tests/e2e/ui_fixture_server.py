"""Serve the real admin UI with fixed API responses for interaction checks."""

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


UI = Path(__file__).resolve().parents[2] / "components" / "admin-ui"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        responses = {
            "/api/models": {"models": [
                {"id": "keeplane-visual-trial", "provider": "custom", "kind": "fixture",
                 "approved": True, "approved_classes": ["Public"], "key_choice": "none",
                 "owned_by_keeplane": True},
                {"id": "outside-visual-trial", "provider": "custom", "kind": "fixture",
                 "approved": True, "approved_classes": ["Internal"], "key_choice": "none",
                 "owned_by_keeplane": False},
                {"id": "cloud-visual-trial", "provider": "OpenAI", "kind": "cloud",
                 "approved": True, "approved_classes": ["Public"], "key_choice": "shared",
                 "owned_by_keeplane": True},
            ]},
            "/api/data-classes": {"classes": [
                {"name": "Public"}, {"name": "Internal"}, {"name": "Confidential"}]},
            "/api/identity": {"username": "visual-trial-admin"},
        }
        if self.path in responses:
            return self.json_response(200, responses[self.path])
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/runners/models":
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            return self.json_response(200, {"models": ["trial-model"]})
        self.json_response(404, {"error": "Fixture endpoint not available"})

    def json_response(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(("127.0.0.1", 14210), partial(Handler, directory=str(UI))).serve_forever()
