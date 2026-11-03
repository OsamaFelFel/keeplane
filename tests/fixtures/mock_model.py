"""Deterministic local OpenAI-compatible upstream for ADR 008 evaluation.

This is a test fixture, never a Keeplane runtime component. It uses only Python's
standard library and sends no outbound requests.
"""

import argparse
import json
import time
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# A streamed request whose messages contain this marker gets a slow reply:
# SLOW_STREAM_CHUNKS content pieces, one every SLOW_STREAM_DELAY seconds, sent
# as they are written. It lets a live check stop a gateway copy while the
# reply is still streaming through it.
SLOW_STREAM_MARKER = "keeplane-slow-stream"
SLOW_STREAM_CHUNKS = 30
SLOW_STREAM_DELAY = 0.5


def slow_stream_pieces(count=SLOW_STREAM_CHUNKS):
    return [f"part{index:02d} " for index in range(1, count + 1)]


def slow_stream_text(count=SLOW_STREAM_CHUNKS):
    """The whole answer a slow stream sends when nothing interrupts it."""
    return "".join(slow_stream_pieces(count))


def wants_slow_stream(request):
    messages = request.get("messages")
    return isinstance(messages, list) and any(
        isinstance(message, dict)
        and isinstance(message.get("content"), str)
        and SLOW_STREAM_MARKER in message["content"]
        for message in messages
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = []
    calls_lock = Lock()
    slow_stream_chunks = SLOW_STREAM_CHUNKS
    slow_stream_delay = SLOW_STREAM_DELAY

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ok"})
        elif self.path == "/v1/models":
            self.reply(
                200,
                {"object": "list", "data": [{"id": "mock-local", "object": "model"}]},
            )
        elif self.path == "/calls":
            with self.calls_lock:
                self.reply(
                    200,
                    {
                        "count": len(self.calls),
                        "models": [call["model"] for call in self.calls],
                    },
                )
        else:
            self.reply(404, {"error": "unknown path"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self.reply(400, {"error": "invalid JSON"})
            return
        if self.path != "/v1/chat/completions":
            self.reply(404, {"error": "unknown path"})
            return
        model = request.get("model", "unknown")
        with self.calls_lock:
            self.calls.append({"model": model})
        if model == "__keeplane_no_answer_trial__":
            self.reply(503, {"error": "intentional no-answer registration test"})
            return
        if request.get("stream") and wants_slow_stream(request):
            self.slow_stream(model)
            return
        if request.get("stream"):
            chunks = [
                {
                    "id": "mock-1",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "mock "},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "mock-1",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "answer"},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "mock-1",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            ]
            data = (
                b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks)
                + b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if request.get("tools"):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_mock",
                        "type": "function",
                        "function": {
                            "name": request["tools"][0]["function"]["name"],
                            "arguments": '{"value":1}',
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "mock answer"}
            finish_reason = "stop"
        self.reply(
            200,
            {
                "id": "mock-1",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {"index": 0, "message": message, "finish_reason": finish_reason}
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 2,
                    "total_tokens": 4,
                },
            },
        )

    def slow_stream(self, model):
        """Send each piece as its own HTTP chunk, pausing between pieces."""

        def event(delta, finish_reason=None):
            chunk = {
                "id": "mock-slow",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [
                    {"index": 0, "delta": delta, "finish_reason": finish_reason}
                ],
            }
            return b"data: " + json.dumps(chunk).encode() + b"\n\n"

        def send(data):
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for index, piece in enumerate(slow_stream_pieces(self.slow_stream_chunks)):
                if index:
                    time.sleep(self.slow_stream_delay)
                delta = {"content": piece}
                if not index:
                    delta["role"] = "assistant"
                send(event(delta))
            send(event({}, "stop"))
            send(b"data: [DONE]\n\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # The caller went away mid-reply, as when a gateway copy stops.
            self.close_connection = True

    def reply(self, status, data):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
