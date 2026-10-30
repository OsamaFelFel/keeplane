"""Fixed test-only TLS routes; the client never joins the server network."""

import json
import socket
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import BaseRequestHandler
from threading import Event, Thread
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, build_opener

from installed_cli_tls import Relay, forward


class Connection(BaseRequestHandler):
    def handle(self):
        self.request.settimeout(30)
        try:
            host, port = self.server.upstream
            # Own the raw socket even if TLS wrapping fails.
            with socket.create_connection((host, port), timeout=30) as upstream:  # noqa: SIM117
                with (
                    upstream,
                    self.server.context.wrap_socket(
                        self.request, server_side=True
                    ) as downstream,
                ):
                    pump = Thread(
                        target=forward, args=(downstream, upstream), daemon=True
                    )
                    pump.start()
                    forward(upstream, downstream)
                    downstream.close()
                    pump.join(timeout=1)
        except OSError:
            pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Status(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/fixture/status":
            self.send_error(404)
            return
        try:
            # Fixed read-only observation; no client headers or body reach the provider.
            with self.server.opener.open(
                "https://model:18080/fixture/status", timeout=3
            ) as response:
                raw = response.read(65537)
            data = json.loads(raw)
            if (
                len(raw) > 65536
                or not isinstance(data, dict)
                or set(data) != {"contacts", "tools", "failures", "probes"}
            ):
                raise ValueError
        except (OSError, ValueError, TypeError, RecursionError):
            self.send_error(503, "Fixture observation unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def deny(self):
        self.send_error(405)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = deny


if __name__ == "__main__":
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain("/front-tls/front.pem", "/front-tls/front.key")
    for port, host, upstream in (
        (8443, "app", 3000),
        (5443, "gateway", 5000),
    ):
        relay = Relay(("0.0.0.0", port), Connection)
        relay.context, relay.upstream = context, (host, upstream)
        Thread(target=relay.serve_forever, daemon=True).start()
    observer = ThreadingHTTPServer(("0.0.0.0", 18443), Status)
    observer.opener = build_opener(
        ProxyHandler({}),
        NoRedirects(),
        HTTPSHandler(context=ssl.create_default_context(cafile="/ca.pem")),
    )
    observer.socket = context.wrap_socket(observer.socket, server_side=True)
    Thread(target=observer.serve_forever, daemon=True).start()
    Event().wait()
