"""Small model API fixture for PostgreSQL persistence tests, without policy claims."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            return self.reply(200, {"data": [{"id": "local-fixture"}]})
        if self.path == "/api/config/resources/llm.model":
            return self.reply(200, {"resources": []})
        if self.path == "/api/runtime":
            return self.reply(200, {"build": {"version": "postgres-test-fixture"}})
        self.reply(404, {})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/v1/chat/completions":
            return self.reply(200, {"choices": [{"message": {"content": "OK"}}]})
        self.reply(404, {})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 4000), Handler).serve_forever()
