"""The slow-stream fixture and the stream probe the K8S-18 live check uses.

The plain-English cases are SPROBE-01 to SPROBE-04 in stream-probe-cases.md.
Every server is a loopback HTTP server in this process; no gateway is used.
"""

import io
import json
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from tests.fixtures import mock_model
from tests.support import stream_probe

PIECES = 4


class CutHandler(BaseHTTPRequestHandler):
    """Sends two pieces of a streamed answer, then stops as a copy would."""

    protocol_version = "HTTP/1.1"
    clean_end = False

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for piece in mock_model.slow_stream_pieces(2):
            event = {"choices": [{"index": 0, "delta": {"content": piece}}]}
            data = b"data: " + json.dumps(event).encode() + b"\n\n"
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        if self.clean_end:
            # The body ends properly, but without a finish or [DONE].
            self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        self.close_connection = True


class CleanEndHandler(CutHandler):
    clean_end = True


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def fixture_model(monkeypatch):
    monkeypatch.setattr(mock_model.Handler, "slow_stream_chunks", PIECES)
    monkeypatch.setattr(mock_model.Handler, "slow_stream_delay", 0.01)
    monkeypatch.setattr(mock_model.Handler, "log_message", lambda *args: None)
    server = serve(mock_model.Handler)
    yield server
    server.shutdown()


def probe(server, prompt):
    output = io.StringIO()
    with redirect_stdout(output):
        stream_probe.main(
            ["stream_probe.py", "127.0.0.1", str(server.server_port), "m", prompt, "-"]
        )
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    return [line["content"] for line in lines if line["event"] == "chunk"], lines[-1]


def test_sprobe_01_a_slow_stream_arrives_piece_by_piece_and_complete(fixture_model):
    chunks, end = probe(fixture_model, mock_model.SLOW_STREAM_MARKER + " please")
    assert chunks == mock_model.slow_stream_pieces(PIECES)
    assert end == {
        "event": "end",
        "status": 200,
        "content": mock_model.slow_stream_text(PIECES),
        "done": True,
        "finish": "stop",
        "error": None,
    }


def test_sprobe_02_other_streams_keep_the_quick_fixture_answer(fixture_model):
    chunks, end = probe(fixture_model, "fixture")
    assert chunks == ["mock ", "answer"]
    assert end["done"] is True and end["content"] == "mock answer"


@pytest.mark.parametrize("handler", [CutHandler, CleanEndHandler])
def test_sprobe_03_a_stream_cut_short_is_never_reported_complete(handler):
    server = serve(handler)
    try:
        chunks, end = probe(server, "anything")
    finally:
        server.shutdown()
    received = mock_model.slow_stream_text(2)
    assert "".join(chunks) == end["content"] == received
    assert end["done"] is False and end["finish"] is None
    if handler is CutHandler:
        # The connection closed mid-body: the probe names the failure.
        assert end["error"] and "IncompleteRead" in end["error"]


def test_sprobe_04_a_refused_or_unreachable_gateway_is_an_error():
    server = serve(mock_model.Handler)
    port = server.server_port
    server.shutdown()
    server.server_close()
    result = stream_probe.stream("127.0.0.1", port, "m", "x", "")
    assert result["status"] is None and result["error"]
    assert result["done"] is False
