"""Test-only TLS byte forwarding; authorization stays in Django/native gateway."""

import socket
import ssl
from socketserver import BaseRequestHandler, ThreadingTCPServer
from threading import Event, Thread


def forward(source, destination):
    try:
        while data := source.recv(65536):
            destination.sendall(data)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Relay(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Connection(BaseRequestHandler):
    def handle(self):
        self.request.settimeout(30)
        try:
            with (
                self.server.context.wrap_socket(
                    self.request, server_side=True
                ) as downstream,
                socket.create_connection(
                    ("gateway", self.server.upstream), timeout=30
                ) as upstream,
            ):
                pump = Thread(target=forward, args=(downstream, upstream), daemon=True)
                pump.start()
                forward(upstream, downstream)
                downstream.close()
                pump.join(timeout=1)
        except OSError:
            pass


if __name__ == "__main__":
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain("/tls-private/cert.pem", "/tls-private/key.pem")
    for port, upstream in ((8443, 8090), (5443, 5000), (18443, 18080)):
        relay = Relay(("0.0.0.0", port), Connection)
        relay.context, relay.upstream = context, upstream
        Thread(target=relay.serve_forever, daemon=True).start()
    Event().wait()
