"""Disposable authenticated endpoint for the Docker preview; forwards to Qwen.

This is test infrastructure, not a provider adapter for customer deployment.
It accepts only one route and never records request bodies or credentials.
"""

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


KEY = os.environ["PREVIEW_PROVIDER_KEY"]
UPSTREAM = "http://qwen:8080/v1/chat/completions"


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ready"})
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.reply(404, {"error": "Not found"})
        if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {KEY}"):
            return self.reply(401, {"error": "Invalid provider key"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 64 * 1024:
                return self.reply(400, {"error": "Invalid request size"})
            payload = self.rfile.read(size)
            request = Request(UPSTREAM, data=payload, headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=120) as response:
                body = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as error:
            self.reply(error.code, {"error": "Local model rejected the request"})
        except (URLError, TimeoutError):
            self.reply(503, {"error": "Local model unavailable"})
        except ValueError:
            self.reply(400, {"error": "Invalid request size"})

    def log_message(self, _format, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 18081), Handler).serve_forever()
