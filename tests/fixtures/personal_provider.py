"""Synthetic HTTPS provider; keys are checked before an optional tool responder."""

import json
import ssl
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import ClassVar


class PersonalProvider(BaseHTTPRequestHandler):
    keys: ClassVar[dict[str, str]] = {}
    upstream_models: ClassVar[set[str]] = {"fixture-personal"}
    state: ClassVar[dict] = {"contacts": [], "failures": 0, "probes": 0}
    lock = Lock()

    def log_message(self, *args):
        pass

    def snapshot(self):
        with self.lock:
            return deepcopy(self.state)

    def answer(self, status, body, content_type="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/fixture/status":
            self.answer(200, self.snapshot())
        else:
            self.answer(404, {})

    def respond(self, body, protocol, owner_label):
        """Subclass only this method; it runs after protocol and secrecy checks."""
        return False

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            anthropic = self.path == "/v1/messages"
            supplied = (
                self.headers.get("x-api-key")
                if anthropic
                else self.headers.get("Authorization", "").removeprefix("Bearer ")
            )
            if not supplied:
                with self.lock:
                    self.state["probes"] += 1
                self.answer(401, {"error": "Synthetic provider needs a key"})
                return
            owner = next(
                (name for name, value in self.keys.items() if supplied == value), None
            )
            valid = (
                owner is not None
                and self.path in ("/v1/messages", "/v1/chat/completions")
                and body.get("model") in self.upstream_models
                and not any(
                    name.lower().startswith(("x-keeplane-", "x-opencode-"))
                    or name.lower() in ("cookie", "x-provider-authorization")
                    for name in self.headers
                )
                and (
                    not anthropic
                    or (
                        not self.headers.get("Authorization")
                        and self.headers.get("anthropic-version") == "2023-06-01"
                    )
                )
                and (anthropic or not self.headers.get("x-api-key"))
                and len(
                    self.headers.get_all(
                        "x-api-key" if anthropic else "Authorization", []
                    )
                )
                == 1
                and (
                    not anthropic
                    or self.headers.get_all("anthropic-version") == ["2023-06-01"]
                )
            )
            protocol = "anthropic" if anthropic else "openai"
            with self.lock:
                self.state["failures"] += int(not valid)
                self.state["contacts"].append(
                    {
                        "provider": protocol,
                        "key_owner": owner,
                        "validation": body.get(
                            "max_tokens", body.get("max_completion_tokens")
                        )
                        == 1,
                    }
                )
            if not valid:
                self.answer(403, {"error": "Synthetic provider oracle failed"})
                return
            if self.respond(body, protocol, owner):
                return
            if anthropic:
                self.answer(
                    200,
                    {
                        "id": "synthetic",
                        "type": "message",
                        "role": "assistant",
                        "model": body["model"],
                        "content": [{"type": "text", "text": "OK"}],
                        "stop_reason": "end_turn",
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                )
            else:
                self.answer(
                    200,
                    {
                        "id": "synthetic",
                        "object": "chat.completion",
                        "model": body["model"],
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "OK"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    },
                )
        except (AssertionError, KeyError, TypeError, ValueError):
            with self.lock:
                self.state["failures"] += 1
            self.answer(400, {"error": "Synthetic provider request was malformed"})


def serve(handler=PersonalProvider):
    handler.keys = json.loads(Path("/model-tls/expected.json").read_text())
    server = ThreadingHTTPServer(("0.0.0.0", 18080), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("/model-tls/provider.pem", "/model-tls/provider.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
