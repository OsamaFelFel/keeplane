"""The fixture model's paced stream, which the live copy-stops cases rely on.

Cases are in model-fixture-stream-cases.md.
"""

import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from tests.fixtures import mock_model


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(mock_model.Handler, "pause", 0.05)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), mock_model.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def ask(port, prompt, stream=True):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(
        "POST",
        "/v1/chat/completions",
        json.dumps(
            {
                "model": "mock-local",
                "stream": stream,
                "messages": [{"role": "user", "content": prompt}],
            }
        ),
        {"Content-Type": "application/json"},
    )
    return connection, connection.getresponse()


def events(response):
    for raw in response:
        line = raw.decode().strip()
        if line.startswith("data:"):
            yield line[5:].strip(), time.monotonic()


def test_mfs_01_the_slow_prompt_streams_paced_chunks_then_finishes(server):
    connection, response = ask(server, mock_model.SLOW_STREAM_PROMPT)
    assert response.status == 200
    assert response.getheader("Transfer-Encoding") == "chunked"
    assert response.getheader("Content-Length") is None
    received = list(events(response))
    connection.close()
    assert received[-1][0] == "[DONE]"
    chunks = [json.loads(data) for data, _ in received[:-1]]
    assert len(chunks) == mock_model.SLOW_STREAM_CHUNKS + 1
    text = "".join(
        chunk["choices"][0]["delta"].get("content", "") for chunk in chunks
    )
    assert text == mock_model.slow_stream_text()
    assert [chunk["choices"][0]["finish_reason"] for chunk in chunks][-2:] == [
        None,
        "stop",
    ]
    # Paced: the reply takes about chunks x pause, not one burst.
    assert received[-1][1] - received[0][1] >= 0.04 * mock_model.SLOW_STREAM_CHUNKS


def test_mfs_02_a_caller_leaving_mid_stream_does_not_stop_the_fixture(server):
    connection, response = ask(server, mock_model.SLOW_STREAM_PROMPT)
    first = response.fp.readline()
    assert first
    connection.close()
    # Other prompts keep their immediate answers.
    connection, response = ask(server, "fixture")
    received = [data for data, _ in events(response)]
    connection.close()
    assert received[-1] == "[DONE]"
    assert len(received) == 4
    connection, response = ask(server, "fixture", stream=False)
    body = json.loads(response.read())
    connection.close()
    assert body["choices"][0]["message"]["content"] == "mock answer"
