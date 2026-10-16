"""Real local TLS routing and refusal to delete a foreign namespace."""

import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

import pytest

from tests.fixtures.helm_sign_in import HelmSignIn

ROOT = Path(__file__).resolve().parents[2]


def fixture_at(directory):
    return HelmSignIn(
        directory,
        ROOT,
        "unused:fixture",
        "sha256:" + "a" * 64,
        "/unused",
        "kind-keeplane-netpol",
        "/unused",
    )


def test_verified_tls_edge_selects_real_copy_and_retains_no_request_secrets(tmp_path):
    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(str(self.server.copy).encode())

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Backend) for _ in (0, 1)]
    fixture = fixture_at(tmp_path)
    try:
        for index, server in enumerate(servers):
            server.copy = index
            threading.Thread(target=server.serve_forever, daemon=True).start()
        fixture.certificates()
        fixture.edge.ports = [server.server_port for server in servers]
        threading.Thread(target=fixture.edge.serve_forever, daemon=True).start()
        fixture.serving = True
        untrusted = build_opener(
            ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context())
        )
        with pytest.raises(URLError) as failure:
            untrusted.open(fixture.origin + "/", timeout=3)
        assert isinstance(failure.value.reason, ssl.SSLCertVerificationError)
        trusted = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context(cafile=str(fixture.ca))),
        )
        for index in (0, 1):
            fixture.route(index)
            request = Request(
                fixture.origin + "/api/runtime/session?private=synthetic-code",
                headers={"Authorization": "Bearer synthetic-credential"},
            )
            with trusted.open(request, timeout=3) as response:
                assert response.read() == str(index).encode()
        assert fixture.edge.observations == [
            {"copy": 0, "path": "/api/runtime/session", "status": 200},
            {"copy": 1, "path": "/api/runtime/session", "status": 200},
        ]
    finally:
        fixture.close()
        for server in servers:
            server.shutdown()
            server.server_close()


def test_cleanup_refuses_a_namespace_without_this_fixtures_ownership_label(tmp_path):
    fixture = fixture_at(tmp_path)
    fixture.created = True
    actions = []

    def kube(*args):
        actions.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {"metadata": {"labels": {"keeplane-test-owner": "someone-else"}}}
            ).encode(),
            b"",
        )

    fixture.kube = kube
    with pytest.raises(AssertionError):
        fixture.close()
    assert all("delete" not in action for action in actions)
    assert not fixture.report["cleaned"]
