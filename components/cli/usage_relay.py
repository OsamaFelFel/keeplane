"""Count the token usage in each gateway answer on its way to the coding runtime.

ADR 029: the CLI reports the token counts it sees in the gateway's answers.
The runtime doesn't print every model call (OpenCode 2.0.27 prints no step
events for a turn's last call, nor any for a subagent's), so `keeplane code`
puts this relay between the runtime and the gateway for one turn.

The relay listens on 127.0.0.1 only, on a port the system picks. It sends each
request on to the gateway as it came, with the runtime's own headers (its
Keeplane grant included) and nothing added: it holds no credential. It only
asks for an uncompressed answer, so it can read it. It passes each answer back
as it arrives, streamed or not, and reads the ``usage`` object from it. It
keeps nothing else: no prompt, answer or header.
"""

import hmac
import http.client
import json
import socket
import socketserver
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

# Headers that belong to one connection, not to the request or answer.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-connection",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "expect",
        "host",
        "content-length",
        "accept-encoding",
    }
)
MAX_REQUEST = 64 * 1024 * 1024
# A whole (not streamed) answer is read for its usage up to this size.
MAX_ANSWER = 16 * 1024 * 1024
# A streamed event line longer than this is passed on but not read.
MAX_LINE = 1024 * 1024
CHUNK = 64 * 1024
COUNTS = ("input_tokens", "output_tokens", "requests", "requests_without_usage")
GATEWAY_UNREACHABLE = (
    b'{"error":{"message":"Keeplane could not reach the gateway.",'
    b'"type":"keeplane_relay"}}'
)


NOT_THIS_TURN = (
    b'{"error":{"message":"This relay serves only this Keeplane turn.",'
    b'"type":"keeplane_relay"}}'
)


class RelayError(ValueError):
    pass


def tokens(usage):
    """(input, output) from an OpenAI-compatible ``usage`` object, or None.

    ``prompt_tokens`` already includes cached input and ``completion_tokens``
    includes reasoning, so neither detail is added again. The Responses API
    names them ``input_tokens`` and ``output_tokens``.
    """
    if not isinstance(usage, dict):
        return None

    def whole(*names):
        for name in names:
            value = usage.get(name)
            if type(value) is int and value >= 0:
                return value
        return None

    used_in = whole("prompt_tokens", "input_tokens")
    used_out = whole("completion_tokens", "output_tokens")
    if used_in is None and used_out is None:
        return None
    return used_in or 0, used_out or 0


def usage_in(event):
    if not isinstance(event, dict):
        return None
    found = tokens(event.get("usage"))
    if found is None and isinstance(event.get("response"), dict):
        found = tokens(event["response"].get("usage"))  # Responses API stream
    return found


class Reader:
    """Reads the usage of one answer from the bytes passed back to the runtime."""

    def __init__(self, streamed):
        self.streamed = streamed
        self.buffer = bytearray()
        self.skipping = False
        self.found = None

    def feed(self, data):
        if not self.streamed:
            if len(self.buffer) + len(data) > MAX_ANSWER:
                self.skipping = True
            if not self.skipping:
                self.buffer += data
            return
        self.buffer += data
        while True:
            end = self.buffer.find(b"\n")
            if end < 0:
                break
            line = bytes(self.buffer[:end])
            del self.buffer[: end + 1]
            if self.skipping:
                self.skipping = False  # the rest of an overlong line
                continue
            self.line(line)
        if len(self.buffer) > MAX_LINE:
            self.buffer.clear()
            self.skipping = True

    def line(self, line):
        line = line.strip()
        if not line.startswith(b"data:"):
            return
        payload = line[5:].strip()
        if not payload or payload == b"[DONE]":
            return
        try:
            event = json.loads(payload)
        except (ValueError, RecursionError):
            return
        found = usage_in(event)
        if found is not None:
            # A provider that repeats usage in later chunks sends running
            # totals, so the last one counts.
            self.found = found

    def finish(self):
        if self.streamed:
            if not self.skipping and self.buffer:
                self.line(bytes(self.buffer))
        elif not self.skipping and self.buffer:
            try:
                self.found = usage_in(json.loads(bytes(self.buffer)))
            except (ValueError, RecursionError):
                pass
        self.buffer.clear()
        return self.found


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "keeplane-relay"
    sys_version = ""

    def log_message(self, *args):
        pass  # Nothing about a request is written anywhere.

    def do_POST(self):
        self.relay.forward(self)

    do_GET = do_PUT = do_PATCH = do_DELETE = do_POST


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer looks up this host's name, a DNS query; only bind.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Relay:
    """One turn's relay to ``gateway``; use it as a context manager.

    Only requests that carry this turn's ``grant`` as their bearer are sent
    on. Another local user or program can reach the port during the turn, but
    any other request is refused with 403: not sent on and not counted.

    ``url`` is the address for the runtime's provider. ``usage()`` gives the
    counts per model, keyed by the model each request named.
    """

    def __init__(self, gateway, timeout=300, *, grant):
        if not isinstance(grant, str) or not grant:
            raise RelayError("The relay needs this turn's grant.")
        self.authorization = ("Bearer " + grant).encode("utf-8")
        url = urlsplit(gateway)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise RelayError("The relay needs the gateway's HTTP(S) address.")
        self.scheme, self.host, self.port = url.scheme, url.hostname, url.port
        self.netloc = url.netloc
        self.prefix = url.path.rstrip("/")
        self.timeout = timeout
        self.lock = threading.Condition()
        self.counts = {}
        self.active = set()
        self.upstreams = []  # (host, port) of every connection made, for checks
        # Requests the gateway never answered (009-15): `keeplane code` then
        # says the gateway can't be reached, not that the model is down.
        self.unreachable = 0
        handler = type("RelayHandler", (Handler,), {"relay": self})
        self.server = Server(("127.0.0.1", 0), handler)
        self.url = (
            "http://127.0.0.1:" + str(self.server.server_address[1]) + self.prefix
        )
        self.thread = None

    def __enter__(self):
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        self.thread.start()
        return self

    def __exit__(self, kind, *args):
        # A turn that was cancelled or failed isn't reported: don't wait.
        self.close(wait=0 if kind else 5.0)

    def close(self, wait=5.0):
        """Stop listening, then let answers still in flight finish counting."""
        if self.thread is not None:
            self.server.shutdown()
            self.thread.join(timeout=5)
            self.thread = None
        self.server.server_close()
        deadline = time.monotonic() + wait
        with self.lock:
            while self.active and time.monotonic() < deadline:
                self.lock.wait(deadline - time.monotonic())
            stuck = list(self.active)
        for connection in stuck:  # The runtime is gone; unblock their reads.
            try:
                if connection.sock is not None:
                    connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        with self.lock:
            self.lock.wait_for(lambda: not self.active, timeout=1)

    def usage(self):
        with self.lock:
            return {model: dict(row) for model, row in self.counts.items()}

    def record(self, model, found):
        with self.lock:
            row = self.counts.setdefault(model, dict.fromkeys(COUNTS, 0))
            row["requests"] += 1
            if found is None:
                row["requests_without_usage"] += 1
            else:
                row["input_tokens"] += found[0]
                row["output_tokens"] += found[1]

    def connection(self):
        if self.scheme == "https":
            return http.client.HTTPSConnection(
                self.host,
                self.port,
                timeout=self.timeout,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def ours(self, client):
        values = client.headers.get_all("Authorization") or []
        return len(values) == 1 and hmac.compare_digest(
            values[0].encode("utf-8", "replace"), self.authorization
        )

    def forward(self, client):
        if not self.ours(client):
            # Not this turn's runtime: never sent on, never counted.
            client.close_connection = True
            reply(client, 403, NOT_THIS_TURN)
            return
        path = client.path
        if not path.startswith("/") or not (
            path == self.prefix
            or path.startswith((self.prefix + "/", self.prefix + "?"))
        ):
            client.send_error(404)
            return
        try:
            body = request_body(client)
        except RelayError:
            client.send_error(413)
            client.close_connection = True
            return
        model = None
        if client.command == "POST" and body:
            try:
                model = json.loads(body).get("model")
            except (ValueError, RecursionError, AttributeError):
                model = None
        if not isinstance(model, str) or not 0 < len(model) <= 256:
            model = None
        upstream = self.connection()
        with self.lock:
            self.active.add(upstream)
            self.upstreams.append(
                (self.host, self.port or (443 if self.scheme == "https" else 80))
            )
        try:
            self.exchange(client, upstream, body, model)
        finally:
            upstream.close()
            with self.lock:
                self.active.discard(upstream)
                self.lock.notify_all()

    def exchange(self, client, upstream, body, model):
        try:
            upstream.putrequest(
                client.command, client.path, skip_host=True, skip_accept_encoding=True
            )
            upstream.putheader("Host", self.netloc)
            for name, value in client.headers.items():
                if name.lower() not in HOP_BY_HOP:
                    upstream.putheader(name, value)
            upstream.putheader("Accept-Encoding", "identity")
            if body is not None:
                upstream.putheader("Content-Length", str(len(body)))
            upstream.endheaders(body)
            answer = upstream.getresponse()
        except (OSError, http.client.HTTPException):
            with self.lock:
                self.unreachable += 1
            reply(client, 502, GATEWAY_UNREACHABLE)
            return
        counted = model is not None and 200 <= answer.status < 300
        streamed = (
            (answer.getheader("Content-Type") or "")
            .lower()
            .startswith("text/event-stream")
        )
        reader = Reader(streamed)
        try:
            client.send_response_only(answer.status, answer.reason)
            for name, value in answer.getheaders():
                if name.lower() not in HOP_BY_HOP:
                    client.send_header(name, value)
            empty = answer.status in (204, 304) or answer.status < 200
            length = answer.getheader("Content-Length")
            whole = length is not None and not answer.chunked and length.isdigit()
            if empty:
                client.send_header("Content-Length", "0")
            elif whole:
                client.send_header("Content-Length", length)
            else:
                client.send_header("Transfer-Encoding", "chunked")
            client.end_headers()
            while not empty:
                data = answer.read1(CHUNK)
                if not data:
                    break
                if counted:
                    reader.feed(data)
                client.wfile.write(
                    data if whole else b"%x\r\n%s\r\n" % (len(data), data)
                )
                client.wfile.flush()
            if not empty and not whole:
                client.wfile.write(b"0\r\n\r\n")
                client.wfile.flush()
        except (OSError, http.client.HTTPException):
            client.close_connection = True
        finally:
            if counted:
                self.record(model, reader.finish())


def request_body(client):
    """The request's body as bytes, or None when it has none."""
    if "chunked" in (client.headers.get("Transfer-Encoding") or "").lower():
        body = bytearray()
        while True:
            size = client.rfile.readline(1024).split(b";")[0].strip()
            try:
                size = int(size, 16)
            except ValueError:
                raise RelayError("Malformed chunked request.") from None
            if size == 0:
                while client.rfile.readline(1024) not in (b"\r\n", b"\n", b""):
                    pass
                return bytes(body)
            if len(body) + size > MAX_REQUEST:
                raise RelayError("Request too large.")
            body += client.rfile.read(size)
            client.rfile.readline(1024)
    length = client.headers.get("Content-Length")
    if length is None:
        return None
    if not length.isdigit() or int(length) > MAX_REQUEST:
        raise RelayError("Request too large.")
    return client.rfile.read(int(length))


def reply(client, status, payload):
    try:
        client.send_response_only(status)
        client.send_header("Content-Type", "application/json")
        client.send_header("Content-Length", str(len(payload)))
        client.end_headers()
        client.wfile.write(payload)
        client.wfile.flush()
    except OSError:
        client.close_connection = True
