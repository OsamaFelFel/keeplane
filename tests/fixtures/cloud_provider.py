"""Authenticated OpenAI/Anthropic fixture for the protected Docker trial.

This is a test endpoint, not a production provider adapter. It accepts the
preview's shared trial key, and a developer's own key once a test has marked
that key's SHA-256 as accepted in ``OWN_KEYS_FILE`` (a test turns it to
refused there, as a provider revoking it would). It records call counts and a
SHA-256 of each key it was sent, and never prints, stores or returns a key.

With ``TLS_CERT_FILE`` and ``TLS_KEY_FILE`` it serves HTTPS on 18443, reading
the certificate for each connection, so a renewed test certificate needs no
restart. Without them it serves plain HTTP on 18082, as the kind preview does.
"""

import hashlib
import hmac
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import ClassVar

KEY_FILE = Path(os.environ["TRIAL_KEY_FILE"])
OWN_KEYS_FILE = Path(os.environ.get("OWN_KEYS_FILE", "/tmp/own-keys.json"))
CERT_FILE, KEY_FILE_TLS = (
    os.environ.get("TLS_CERT_FILE"),
    os.environ.get("TLS_KEY_FILE"),
)


def digest(key):
    return hashlib.sha256(key.encode()).hexdigest()


def own_key_state(key):
    """``accepted`` or ``refused`` for a developer key a test marked, else None."""
    try:
        marked = json.loads(OWN_KEYS_FILE.read_text())
    except (OSError, ValueError):
        return None
    state = marked.get(digest(key)) if isinstance(marked, dict) else None
    return state if state in ("accepted", "refused") else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    count = 0
    # SHA-256 of each key sent -> {"accepted": n, "refused": n}; never a key.
    keys: ClassVar[dict] = {}
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
                return self.reply(
                    200,
                    {
                        "count": type(self).count,
                        "keys": json.loads(json.dumps(type(self).keys)),
                    },
                )
        return self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/v1/messages"):
            return self.reply(404, {"error": "Not found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            # A coding runtime's request, with its tool definitions, can be large.
            if not 1 <= size <= 1048576:
                return self.reply(400, {"error": "Invalid request size"})
            body = json.loads(self.rfile.read(size))
            expected = KEY_FILE.read_text().strip()
        except (ValueError, OSError):
            return self.reply(503, {"error": "Fixture unavailable"})
        authorization = self.headers.get("Authorization", "")
        sent = self.headers.get("x-api-key") or (
            authorization[7:] if authorization.startswith("Bearer ") else ""
        )
        accepted = bool(sent) and (
            hmac.compare_digest(sent, expected) or own_key_state(sent) == "accepted"
        )
        with self.lock:
            if sent:
                seen = type(self).keys.setdefault(
                    digest(sent), {"accepted": 0, "refused": 0}
                )
                seen["accepted" if accepted else "refused"] += 1
            if accepted:
                type(self).count += 1
        if not accepted:
            return self.reply(401, {"error": "Provider key refused"})
        model = body.get("model", "mock-cloud")
        if self.path == "/v1/messages":
            return self.reply(
                200,
                {
                    "id": "msg_cloud_fixture",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": "mock cloud answer"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 2, "output_tokens": 3},
                },
            )
        if body.get("stream"):
            return self.stream(model, body)
        return self.reply(
            200,
            {
                "id": "cloud-fixture",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "mock cloud answer",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            },
        )

    def stream(self, model, body):
        """The same answer as server-sent events, with usage when asked for."""
        head = {
            "id": "cloud-fixture",
            "object": "chat.completion.chunk",
            "model": model,
        }
        events = [
            {
                **head,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "mock cloud answer"},
                        "finish_reason": "stop",
                    }
                ],
            }
        ]
        if (body.get("stream_options") or {}).get("include_usage") is True:
            events.append(
                {
                    **head,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )
        payload = b"".join(
            b"data: " + json.dumps(event).encode() + b"\n\n" for event in events
        )
        payload += b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        pass


class TLSServer(ThreadingHTTPServer):
    """HTTPS with the certificate as it is on disk when each connection opens."""

    def get_request(self):
        connection, address = super().get_request()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            context.load_cert_chain(CERT_FILE, KEY_FILE_TLS)
        except (OSError, ssl.SSLError):
            connection.close()
            raise
        # The handshake runs in the request's own thread, not the accept loop.
        return context.wrap_socket(
            connection, server_side=True, do_handshake_on_connect=False
        ), address

    def handle_error(self, request, client_address):
        pass  # A client that doesn't trust the test CA just disconnects.


if __name__ == "__main__":
    if CERT_FILE and KEY_FILE_TLS:
        TLSServer(("0.0.0.0", 18443), Handler).serve_forever()
    else:
        ThreadingHTTPServer(("0.0.0.0", 18082), Handler).serve_forever()
