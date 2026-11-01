"""Read certificate expiry dates for the certificates Keeplane itself checks.

Used by `manage.py check_credentials`. It reads the CA files mounted into an
app copy (the database CA and, with a customer-run HTTPS gateway, the gateway
CA) and the certificates the database server and HTTPS gateways present. It
reports each certificate's subject, SHA-256 fingerprint and expiry date, never
a key. Certificates are public; private keys are never read.

Only the Python standard library is used: the few X.509 fields needed are read
directly from the DER encoding.
"""

import base64
import binascii
import hashlib
import re
import socket
import ssl
import struct
from datetime import datetime, timezone
from urllib.parse import urlsplit

WARNING_DAYS = 30
PEM = re.compile(
    rb"-----BEGIN CERTIFICATE-----\s*(.+?)\s*-----END CERTIFICATE-----", re.DOTALL
)
COMMON_NAME = bytes.fromhex("550403")
POSTGRES_SSL_REQUEST = struct.pack("!II", 8, 80877103)


class CertificateError(ValueError):
    pass


def _element(data, index):
    """Return (tag, content, next index) for the DER element at index."""
    try:
        tag = data[index]
        length = data[index + 1]
        index += 2
        if length & 0x80:
            count = length & 0x7F
            if not 0 < count <= 4:
                raise CertificateError("unsupported length")
            length = int.from_bytes(data[index:index + count], "big")
            index += count
    except IndexError:
        raise CertificateError("truncated certificate") from None
    end = index + length
    if end > len(data):
        raise CertificateError("truncated certificate")
    return tag, data[index:end], end


def _children(data):
    index = 0
    while index < len(data):
        tag, content, index = _element(data, index)
        yield tag, content


def _time(tag, content):
    text = content.decode("ascii")
    if tag == 0x17:  # UTCTime: YYMMDDHHMMSSZ, years 1950-2049
        year = int(text[:2])
        text = str(1900 + year if year >= 50 else 2000 + year) + text[2:]
    elif tag != 0x18:  # GeneralizedTime: YYYYMMDDHHMMSSZ
        raise CertificateError("unsupported time")
    return datetime.strptime(text, "%Y%m%d%H%M%SZ").replace(tzinfo=timezone.utc)


def _common_name(name):
    for _, attributes in _children(name):
        for _, attribute in _children(attributes):
            parts = list(_children(attribute))
            if len(parts) == 2 and parts[0][1] == COMMON_NAME:
                tag, value = parts[1]
                return value.decode("utf-16-be" if tag == 0x1E else "utf-8", "replace")
    return ""


def describe(der):
    """Subject common name, issuer common name, validity and fingerprint."""
    tag, certificate, _ = _element(der, 0)
    if tag != 0x30:
        raise CertificateError("not a certificate")
    tag, tbs, _ = _element(certificate, 0)
    fields = [field for field in _children(tbs) if field[0] != 0xA0]
    if tag != 0x30 or len(fields) < 5:
        raise CertificateError("not a certificate")
    issuer, validity, subject = fields[2][1], fields[3][1], fields[4][1]
    times = list(_children(validity))
    if len(times) != 2:
        raise CertificateError("not a certificate")
    return {
        "subject": _common_name(subject),
        "issuer": _common_name(issuer),
        "not_before": _time(*times[0]),
        "not_after": _time(*times[1]),
        "sha256": hashlib.sha256(der).hexdigest(),
    }


def pem_certificates(data):
    """The DER certificates in a PEM file or bundle, in order."""
    found = []
    for block in PEM.findall(data):
        try:
            found.append(base64.b64decode(b"".join(block.split()), validate=True))
        except (binascii.Error, ValueError):
            raise CertificateError("a certificate block is not valid base64") from None
    return found


def status(details, now, warning_days):
    """A row for the report, with the plain status of one certificate."""
    days = (details["not_after"] - now).total_seconds() / 86400
    if details["not_before"] > now:
        state = "not yet valid"
    elif days < 0:
        state = "expired"
    elif days <= warning_days:
        state = "expires soon"
    else:
        state = "valid"
    return {
        "subject": details["subject"],
        "issuer": details["issuer"],
        "sha256": details["sha256"],
        "expires": details["not_after"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days_left": int(days) if days >= 0 else -int(-days) - 1,
        "status": state,
    }


def ca_file(path, now, warning_days):
    """Report every certificate in a mounted CA file."""
    try:
        with open(path, "rb") as file:
            data = file.read()
    except OSError:
        return {"file": path, "problem": "the CA file cannot be read", "certificates": []}
    try:
        rows = [status(describe(der), now, warning_days) for der in pem_certificates(data)]
    except (CertificateError, UnicodeDecodeError, ValueError):
        return {"file": path, "problem": "the CA file holds a certificate that cannot be read",
                "certificates": []}
    if not rows:
        return {"file": path, "problem": "the CA file holds no certificate", "certificates": []}
    return {"file": path, "certificates": rows}


def _handshake(host, port, context, postgres, timeout):
    with socket.create_connection((host, port), timeout=timeout) as raw:
        if postgres:
            raw.sendall(POSTGRES_SSL_REQUEST)
            if raw.recv(1) != b"S":
                raise ConnectionError("the server does not offer TLS")
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True)


def server_certificate(host, port, context, now, warning_days, *, postgres=False, timeout=5):
    """Report the certificate a server presents and whether `context` trusts it.

    When verification fails, the certificate is read again without verification
    only to report its dates; nothing is sent over that connection.
    """
    row = {"address": f"{host}:{port}"}
    try:
        der = _handshake(host, port, context, postgres, timeout)
        row["trusted"] = True
    except ssl.SSLCertVerificationError as error:
        row["trusted"] = False
        row["problem"] = error.verify_message or "the certificate is not trusted"
        if error.verify_code == 62 or "hostname" in str(error).lower():
            row["problem"] = "the certificate does not match " + host
        unverified = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        unverified.check_hostname = False
        unverified.verify_mode = ssl.CERT_NONE
        try:
            der = _handshake(host, port, unverified, postgres, timeout)
        except (OSError, ssl.SSLError):
            der = None
    except ConnectionError as error:
        return {**row, "trusted": False, "problem": str(error) or "unreachable"}
    except (OSError, ssl.SSLError):
        return {**row, "trusted": False, "problem": "unreachable"}
    if der:
        try:
            row["certificate"] = status(describe(der), now, warning_days)
        except (CertificateError, UnicodeDecodeError, ValueError):
            row["problem"] = row.get("problem") or "the certificate cannot be read"
    return row


def https_address(url):
    """(host, port) for an https URL, or None for any other URL."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return parts.hostname, parts.port or 443


def problems(section, label):
    """Plain sentences for each refused, expired or soon-expiring certificate."""
    found, warnings = [], []
    if section.get("problem"):
        found.append(f"{label}: {section['problem']}.")
    rows = section.get("certificates") or (
        [section["certificate"]] if section.get("certificate") else []
    )
    for row in rows:
        name = row["subject"] or row["sha256"][:16]
        if row["status"] == "expired":
            found.append(f"{label}: certificate {name} expired on {row['expires']}.")
        elif row["status"] == "not yet valid":
            found.append(f"{label}: certificate {name} is not valid yet.")
        elif row["status"] == "expires soon":
            warnings.append(
                f"{label}: certificate {name} expires on {row['expires']} "
                f"({row['days_left']} days left)."
            )
    return found, warnings
