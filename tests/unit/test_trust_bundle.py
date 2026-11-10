"""Cases CO-10 to CO-12 in certificate-operations-cases.md: the app's trust bundle.

prepare_trust_bundle.py runs in the app pods' init container when the chart's
trust.extraCaBundle is set. Each case makes its own CAs with the openssl
command; the "system" CA file is a stand-in for the image's own.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import prepare_trust_bundle as trust
import pytest

from tests.unit.test_certificate_checks import make_ca, make_leaf, tls_server

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None,
    reason="needs the openssl command to make certificates",
)

SCRIPT = Path(trust.__file__)
REFUSAL = "Keeplane can't use trust.extraCaBundle: "
# Calls one HTTPS server with Python's default verification, as the app does.
FETCH = (
    "import sys, urllib.request; "
    "urllib.request.urlopen('https://localhost:' + sys.argv[1], timeout=10).read(); "
    "print('trusted')"
)


def run(*args):
    return subprocess.run(
        (sys.executable, "-I", str(SCRIPT), *map(str, args)),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def trusts(bundle, port):
    """Whether a new Python process with SSL_CERT_FILE=bundle trusts the server."""
    environment = {**os.environ, "SSL_CERT_FILE": str(bundle)}
    environment.pop("SSL_CERT_DIR", None)
    result = subprocess.run(
        (sys.executable, "-I", "-c", FETCH, str(port)),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.stdout.strip() == "trusted"


def test_co_10_the_bundle_is_the_system_cas_then_the_extra_ones(tmp_path, monkeypatch):
    public = make_ca(tmp_path, "public-ca")
    private = make_ca(tmp_path, "private-ca")
    second = make_ca(tmp_path, "second-private-ca")
    system = tmp_path / "system.pem"
    system.write_bytes(public.read_bytes())
    extra = tmp_path / "extra.pem"
    # A bundle as installers write one: a comment line, two CAs, CRLF endings.
    extra.write_bytes(
        b"# Private model endpoint CAs\r\n"
        + private.read_bytes().replace(b"\n", b"\r\n")
        + second.read_bytes()
    )
    output = tmp_path / "out" / "ca-bundle.pem"
    output.parent.mkdir()
    monkeypatch.setattr(trust, "system_bundle", lambda: str(system))
    assert trust.main(["prepare_trust_bundle.py", str(extra), str(output)]) == 0
    written = output.read_bytes()
    # The system file comes first and unchanged; the extra CAs follow it.
    assert written.startswith(public.read_bytes().rstrip(b"\n"))
    assert written.count(b"-----BEGIN CERTIFICATE-----") == 3
    assert b"# Private" not in written and b"\r" not in written
    assert oct(output.stat().st_mode & 0o777) == "0o444"
    assert not list(output.parent.glob("*.partial"))
    make_leaf(tmp_path, "public-ca", "public-server")
    make_leaf(tmp_path, "private-ca", "private-server")
    with (
        tls_server(tmp_path / "public-server.crt", tmp_path / "public-server.key") as a,
        tls_server(
            tmp_path / "private-server.crt", tmp_path / "private-server.key"
        ) as b,
    ):
        # The system CA alone trusts only the public server; the bundle both.
        assert trusts(system, a.port) and not trusts(system, b.port)
        assert trusts(output, a.port) and trusts(output, b.port)


def test_co_11_a_malformed_bundle_stops_the_pod_and_writes_nothing(tmp_path):
    ca = make_ca(tmp_path, "private-ca")
    pem = ca.read_text()
    body = pem.split("\n", 1)[1].rsplit("-----END", 1)[0]
    system = tmp_path / "system.pem"
    system.write_text(pem)
    bundles = {
        "no certificate": ("just text\n", "holds no PEM certificate"),
        "empty": ("", "holds no PEM certificate"),
        "damaged base64": (
            pem.replace(body, body[:40] + "!!!!" + body[44:]),
            "holds a damaged certificate",
        ),
        "not a certificate": (
            pem.replace(body, "AAAA" + body[4:]),
            "holds a damaged certificate",
        ),
        "private key": (
            pem + (tmp_path / "private-ca.key").read_text(),
            "holds a private key",
        ),
        "a CRL": (
            pem + "-----BEGIN X509 CRL-----\nAAAA\n-----END X509 CRL-----\n",
            "holds a X509 CRL block",
        ),
        "too large": (pem + "#" * (1024 * 1024), "is larger than 1 MiB"),
    }
    for name, (content, message) in bundles.items():
        extra = tmp_path / "extra.pem"
        extra.write_text(content)
        output = tmp_path / "ca-bundle.pem"
        try:
            trust.build(extra, output, system=str(system))
        except trust.BundleRefused as error:
            assert message in str(error), name
        else:
            raise AssertionError(f"{name} was accepted")
        assert not output.exists(), name
    # A missing bundle, or an image without system CAs, is refused too: the
    # app would otherwise trust only the extra CAs.
    result = run(tmp_path / "missing.pem", tmp_path / "ca-bundle.pem")
    assert result.returncode == 1
    assert result.stderr.startswith(REFUSAL + "The extra CA bundle can't be read")
    (tmp_path / "extra.pem").write_text(pem)
    (tmp_path / "empty-system.pem").write_text("")
    try:
        trust.build(
            tmp_path / "extra.pem",
            tmp_path / "ca-bundle.pem",
            system=str(tmp_path / "empty-system.pem"),
        )
    except trust.BundleRefused as error:
        assert "system CA file" in str(error) and "holds no certificate" in str(error)
    else:
        raise AssertionError("an empty system CA file was accepted")
    assert not (tmp_path / "ca-bundle.pem").exists()
    assert "PRIVATE KEY" not in result.stderr + result.stdout


def test_co_12_the_real_system_ca_file_is_kept_and_counted(tmp_path):
    ca = make_ca(tmp_path, "private-ca")
    output = tmp_path / "ca-bundle.pem"
    result = run(ca, output)
    system = Path(trust.system_bundle()).read_bytes()
    count = system.count(b"-----BEGIN CERTIFICATE-----")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"System CAs kept: {count}. Extra CAs added: 1."
    assert output.read_bytes().startswith(system.rstrip(b"\n"))
