"""Certificate checks: expiry dates, private CAs and renewal without a restart.

Spec 002 ST1/ST4/ST5, task 002-02 certificate operations. The plain-English
cases CO-01 to CO-10 are in certificate-operations-cases.md. Certificates are
made with the openssl command for each test; nothing is stored in Git.
"""

import json
import shutil
import socket
import ssl
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from common import certificates, credential_check
from components.cli.server_connection import ConnectionError as CliConnectionError
from components.cli.server_connection import account
from integrations.gateway import adapter as gateway_adapter
from integrations.gateway import preflight
from integrations.gateway.adapter import AgentgatewayModelAdapter

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="needs the openssl command to make certificates"
)

CA_CONFIG = """[req]
distinguished_name = dn
prompt = no
x509_extensions = ca
[dn]
CN = {name}
[ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
"""
LEAF_EXTENSIONS = """basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = {names}
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
"""


def openssl(*args, cwd):
    subprocess.run(("openssl", *args), cwd=cwd, check=True, capture_output=True, timeout=60)


def make_ca(directory, name, days=3650):
    (directory / f"{name}.cnf").write_text(CA_CONFIG.format(name=name))
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", str(days),
            "-config", f"{name}.cnf", "-keyout", f"{name}.key", "-out", f"{name}.crt", cwd=directory)
    return directory / f"{name}.crt"


def make_leaf(directory, ca, name, days=90, names="DNS:localhost,IP:127.0.0.1"):
    (directory / f"{name}.ext").write_text(LEAF_EXTENSIONS.format(names=names))
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={name}",
            "-keyout", f"{name}.key", "-out", f"{name}.csr", cwd=directory)
    openssl("x509", "-req", "-in", f"{name}.csr", "-CA", f"{ca}.crt", "-CAkey", f"{ca}.key",
            "-CAcreateserial", "-sha256", "-days", str(days), "-extfile", f"{name}.ext",
            "-out", f"{name}.crt", cwd=directory)
    return directory / f"{name}.crt", directory / f"{name}.key"


def fingerprint(path):
    out = subprocess.run(("openssl", "x509", "-in", str(path), "-noout", "-fingerprint", "-sha256"),
                         check=True, capture_output=True, text=True).stdout
    return out.split("=", 1)[1].strip().replace(":", "").lower()


@pytest.fixture
def pki(tmp_path):
    old = make_ca(tmp_path, "old-ca")
    new = make_ca(tmp_path, "new-ca")
    return SimpleNamespace(dir=tmp_path, old=old, new=new)


class TlsServer:
    """A server presenting a certificate; optionally speaking PostgreSQL's SSLRequest
    first, or answering HTTPS like a gateway."""

    def __init__(self, cert, key, postgres=False, offer_tls=True):
        self.postgres, self.offer_tls = postgres, offer_tls
        self.load(cert, key)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def load(self, cert, key):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.context = context

    def serve(self):
        while True:
            try:
                raw, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self.answer, args=(raw,), daemon=True).start()

    def answer(self, raw):
        with raw:
            try:
                if self.postgres:
                    raw.recv(8)
                    raw.sendall(b"S" if self.offer_tls else b"N")
                    if not self.offer_tls:
                        return
                with self.context.wrap_socket(raw, server_side=True) as tls:
                    if not self.postgres:
                        tls.recv(65536)
                        body = json.dumps({"data": []}).encode()
                        tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                                    b"Content-Length: " + str(len(body)).encode()
                                    + b"\r\nConnection: close\r\n\r\n" + body)
            except (OSError, ssl.SSLError):
                pass

    def close(self):
        self.listener.close()


@contextmanager
def tls_server(*args, **kwargs):
    server = TlsServer(*args, **kwargs)
    try:
        yield server
    finally:
        server.close()


def now():
    return datetime.now(timezone.utc) + timedelta(seconds=1)


def test_co_01_a_ca_bundle_reports_each_certificate_without_key_material(pki):
    bundle = pki.dir / "bundle.crt"
    bundle.write_bytes(pki.old.read_bytes() + pki.new.read_bytes())
    report = certificates.ca_file(str(bundle), now(), 30)
    assert [row["subject"] for row in report["certificates"]] == ["old-ca", "new-ca"]
    assert [row["sha256"] for row in report["certificates"]] == [
        fingerprint(pki.old), fingerprint(pki.new)]
    assert all(row["status"] == "valid" and row["days_left"] >= 3640
               for row in report["certificates"])
    expected = subprocess.run(("openssl", "x509", "-in", str(pki.old), "-noout", "-enddate"),
                              check=True, capture_output=True, text=True).stdout
    assert datetime.strptime(expected.strip().split("=", 1)[1], "%b %d %H:%M:%S %Y %Z").strftime(
        "%Y-%m-%dT%H:%M:%SZ") == report["certificates"][0]["expires"]
    text = json.dumps(report)
    assert "PRIVATE" not in text and "BEGIN" not in text


def test_co_02_expiry_is_reported_as_valid_soon_or_expired(pki):
    details = certificates.describe(certificates.pem_certificates(pki.old.read_bytes())[0])
    end = details["not_after"]
    assert certificates.status(details, end - timedelta(days=45), 30)["status"] == "valid"
    soon = certificates.status(details, end - timedelta(days=12, hours=1), 30)
    assert (soon["status"], soon["days_left"]) == ("expires soon", 12)
    gone = certificates.status(details, end + timedelta(hours=1), 30)
    assert (gone["status"], gone["days_left"]) == ("expired", -1)
    assert certificates.status(details, details["not_before"] - timedelta(days=1), 30)[
        "status"] == "not yet valid"
    refusals, warnings = certificates.problems({"certificates": [soon, gone]}, "Database CA")
    assert warnings == [f"Database CA: certificate old-ca expires on {soon['expires']} (12 days left)."]
    assert refusals == [f"Database CA: certificate old-ca expired on {gone['expires']}."]


@pytest.mark.parametrize("content, problem", [
    (None, "the CA file cannot be read"),
    (b"", "the CA file holds no certificate"),
    (b"-----BEGIN CERTIFICATE-----\nnot base64!\n-----END CERTIFICATE-----\n",
     "the CA file holds a certificate that cannot be read"),
    (b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n",
     "the CA file holds a certificate that cannot be read"),
])
def test_co_03_an_unreadable_ca_file_is_a_refusal(tmp_path, content, problem):
    path = tmp_path / "ca.crt"
    if content is not None:
        path.write_bytes(content)
    report = certificates.ca_file(str(path), now(), 30)
    assert report["problem"] == problem
    assert certificates.problems(report, "Gateway CA")[0] == [f"Gateway CA: {problem}."]


def test_co_04_database_server_certificate_is_checked_as_libpq_checks_it(pki):
    cert, key = make_leaf(pki.dir, "new-ca", "db", days=20)
    with tls_server(cert, key, postgres=True) as server:
        trusted = credential_check.ssl_context_for_database(
            {"sslrootcert": str(pki.new), "sslmode": "verify-full"})
        row = certificates.server_certificate("localhost", server.port, trusted, now(), 30, postgres=True)
        assert row["trusted"] is True
        assert row["certificate"]["subject"] == "db"
        assert row["certificate"]["issuer"] == "new-ca"
        assert row["certificate"]["status"] == "expires soon"
        # Only the configured CA is trusted, as with libpq's sslrootcert.
        other = credential_check.ssl_context_for_database(
            {"sslrootcert": str(pki.old), "sslmode": "verify-full"})
        row = certificates.server_certificate("localhost", server.port, other, now(), 30, postgres=True)
        assert row["trusted"] is False and "unable to get local issuer" in row["problem"]
        assert row["certificate"]["subject"] == "db"  # dates still reported
    cert, key = make_leaf(pki.dir, "new-ca", "wrong-name", names="DNS:elsewhere.example")
    with tls_server(cert, key, postgres=True) as server:
        row = certificates.server_certificate("localhost", server.port, trusted, now(), 30, postgres=True)
        assert row == {**row, "trusted": False, "problem": "the certificate does not match localhost"}
    with tls_server(cert, key, postgres=True, offer_tls=False) as server:
        row = certificates.server_certificate("localhost", server.port, trusted, now(), 30, postgres=True)
        assert row["problem"] == "the server does not offer TLS"


def database(port, ca):
    return SimpleNamespace(vendor="postgresql", settings_dict={
        "HOST": "localhost", "PORT": str(port),
        "OPTIONS": {"sslmode": "verify-full", "sslrootcert": str(ca)}})


def test_co_05_check_credentials_fails_on_an_expired_ca_and_warns_before(pki, monkeypatch):
    cert, key = make_leaf(pki.dir, "new-ca", "db", days=400)
    monkeypatch.delenv("KEEPLANE_GATEWAY_CA_FILE", raising=False)
    gateway = SimpleNamespace(base_url="http://gateway:4000")
    with tls_server(cert, key, postgres=True) as server, \
            patch.object(credential_check, "connection", database(server.port, pki.new)):
        report, refusals, warnings = credential_check.certificate_report([gateway], 30)
        assert set(report) == {"database_ca", "database_server"}  # no TLS to an http gateway
        assert (refusals, warnings) == ([], [])
        end = datetime.strptime(report["database_server"]["certificate"]["expires"],
                                "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        _, refusals, warnings = credential_check.certificate_report(
            [gateway], 30, now=end - timedelta(days=10))
        assert refusals == [] and len(warnings) == 1 and warnings[0].startswith("Database server")
        _, refusals, _ = credential_check.certificate_report(
            [gateway], 30, now=pki_expiry(pki.new) + timedelta(days=1))
        assert any(line.startswith("Database CA: certificate new-ca expired") for line in refusals)
        with patch.object(credential_check, "database_status", return_value="connected"), \
                patch.object(credential_check, "gateway_status", return_value=[]), \
                patch.object(credential_check, "gateway_models", return_value=[]), \
                patch.object(credential_check, "approvals", return_value=[]):
            report, passed = credential_check.check(gateway, [], 30)
            assert passed is True and report["certificate_problems"] == []
            report, passed = credential_check.check(gateway, [], 500)
            assert passed is True and len(report["certificate_warnings"]) == 1
            with patch.object(credential_check, "certificate_report",
                              return_value=({}, ["Database CA: certificate x expired on y."], [])):
                assert credential_check.check(gateway, [], 30)[1] is False


def pki_expiry(path):
    return certificates.describe(certificates.pem_certificates(path.read_bytes())[0])["not_after"]


def test_co_06_https_gateway_with_a_private_ca_renews_without_a_restart(pki, monkeypatch):
    cert, key = make_leaf(pki.dir, "old-ca", "gateway")
    mounted = pki.dir / "mounted-ca.crt"
    monkeypatch.delenv("KEEPLANE_GATEWAY_CA_FILE", raising=False)
    with tls_server(cert, key) as server:
        gateway = AgentgatewayModelAdapter(f"https://localhost:{server.port}", "", "")
        # The image's system CAs do not know a private CA.
        assert gateway.models() == (503, {"error": "Gateway unavailable"})
        monkeypatch.setenv("KEEPLANE_GATEWAY_CA_FILE", str(mounted))
        assert gateway.models() == (503, {"error": "Gateway CA unavailable"})
        mounted.write_bytes(pki.old.read_bytes())
        assert gateway.models() == (200, {"data": []})
        # Rotation: trust both, switch the gateway's certificate, then only the new CA.
        mounted.write_bytes(pki.old.read_bytes() + pki.new.read_bytes())
        assert gateway.models() == (200, {"data": []})
        new_cert, new_key = make_leaf(pki.dir, "new-ca", "gateway-renewed")
        server.load(new_cert, new_key)
        assert gateway.models() == (200, {"data": []})
        mounted.write_bytes(pki.new.read_bytes())
        assert gateway.models() == (200, {"data": []})
        report, refusals, _ = credential_check.certificate_report([gateway], 30)
        assert report["gateway_ca"]["certificates"][0]["subject"] == "new-ca"
        assert report["gateway_servers"][0]["trusted"] is True
        assert report["gateway_servers"][0]["certificate"]["subject"] == "gateway-renewed"
        assert refusals == []
        # A CA that no longer covers the gateway is a refusal, not a silent pass.
        mounted.write_bytes(pki.old.read_bytes())
        assert gateway.models() == (503, {"error": "Gateway unavailable"})
        _, refusals, _ = credential_check.certificate_report([gateway], 30)
        assert refusals and refusals[0].startswith(f"Gateway localhost:{server.port}:")


def test_co_07_gateway_ca_file_is_reloaded_only_when_it_changes(pki, monkeypatch):
    mounted = pki.dir / "ca.crt"
    mounted.write_bytes(pki.old.read_bytes())
    monkeypatch.setenv("KEEPLANE_GATEWAY_CA_FILE", str(mounted))
    first = gateway_adapter.gateway_tls_context()
    assert gateway_adapter.gateway_tls_context() is first
    mounted.write_bytes(pki.new.read_bytes() + pki.old.read_bytes())
    assert gateway_adapter.gateway_tls_context() is not first


def test_co_08_preflight_names_an_untrusted_gateway_certificate(pki, monkeypatch):
    cert, key = make_leaf(pki.dir, "old-ca", "gateway")
    with tls_server(cert, key) as server:
        url = f"https://localhost:{server.port}"
        with patch.object(preflight, "URL", url), patch.object(preflight, "CA_FILE", ""), \
                patch.object(preflight, "EXPECTED_VERSION", "1.6.0"), \
                patch.object(preflight.time, "sleep"):
            passed, message = preflight.check()
            assert passed is False
            assert message.startswith("Gateway TLS certificate is not trusted: ")
        with patch.object(preflight, "URL", url), patch.object(preflight, "CA_FILE", str(pki.old)):
            assert preflight.fetch("/v1/models") == (200, {"data": []})


def test_co_09_cli_trusts_a_private_ca_through_ssl_cert_file(pki, monkeypatch):
    cert, key = make_leaf(pki.dir, "new-ca", "keeplane")
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps({"id": "00000000-0000-4000-8000-000000000001", "username": "dev", "role": "developer"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        server = f"https://localhost:{httpd.server_address[1]}"
        with pytest.raises(CliConnectionError, match="certificate configuration"):
            account(server, "session-credential")
        monkeypatch.setenv("SSL_CERT_FILE", str(pki.new))
        assert account(server, "session-credential")["username"] == "dev"
    finally:
        httpd.shutdown()
        httpd.server_close()
