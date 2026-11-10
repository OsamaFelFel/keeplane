"""Write the app's CA bundle: the image's system CAs plus the installer's extra CAs.

The chart runs this in an init container when ``trust.extraCaBundle`` is set,
then points the app's ``SSL_CERT_FILE`` at the result. The extra CAs are added
after every system CA, so the app keeps trusting everything the image trusts.

With ``--extra-only`` it writes just the checked CA certificates, nothing else
from the source: the managed gateway copies read that file from the folder
their ``SSL_CERT_DIR`` names, beside their own system CA file.

A bundle that holds no certificate, a broken one or a private key stops the
pod before the app or gateway starts, with one line that says why.
"""

import base64
import binascii
import os
import re
import ssl
import sys
from pathlib import Path

PEM = re.compile(
    rb"-----BEGIN ([A-Z0-9 ]+)-----\r?\n(.*?)\r?\n?-----END \1-----", re.DOTALL
)
LIMIT = 1024 * 1024


class BundleRefused(ValueError):
    pass


def certificates(data, where):
    """Each certificate in a PEM bundle, normalised; refuse anything unsafe."""
    if b"PRIVATE KEY-----" in data:
        raise BundleRefused(
            f"{where} holds a private key. Give only CA certificates, never a key."
        )
    found = []
    for kind, body in PEM.findall(data):
        if kind != b"CERTIFICATE":
            raise BundleRefused(
                f"{where} holds a {kind.decode()} block. Give only CA certificates."
            )
        try:
            der = base64.b64decode(b"".join(body.split()), validate=True)
        except (binascii.Error, ValueError):
            raise BundleRefused(f"{where} holds a damaged certificate.") from None
        pem = ssl.DER_cert_to_PEM_cert(der)
        try:
            ssl.create_default_context(cadata=pem)
        except ssl.SSLError:
            raise BundleRefused(f"{where} holds a damaged certificate.") from None
        found.append(pem)
    if not found:
        raise BundleRefused(f"{where} holds no PEM certificate.")
    return found


def read(path, where, limit=LIMIT):
    try:
        with open(path, "rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        raise BundleRefused(f"{where} can't be read at {path}.") from None
    if len(data) > limit:
        raise BundleRefused(f"{where} is larger than {limit // LIMIT} MiB.")
    return data


def system_bundle():
    """The image's own CA file, as OpenSSL finds it without SSL_CERT_FILE."""
    return ssl.get_default_verify_paths().openssl_cafile


def write(output, data):
    target = Path(output)
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(data)
    partial.chmod(0o444)
    os.replace(partial, target)


def build_extra_only(extra, output):
    """Write only the checked extra CAs to ``output``; return how many."""
    added = certificates(read(extra, "The extra CA bundle"), "The extra CA bundle")
    write(output, "".join(added).encode())
    return len(added)


def build(extra, output, system=None):
    """Write system CAs then the extra CAs to ``output``; return both counts."""
    system = system or system_bundle()
    # The system file is copied as it is: Keeplane never edits the image's trust.
    trusted = read(system, "The image's system CA file", 8 * LIMIT)
    count = trusted.count(b"-----BEGIN CERTIFICATE-----")
    if not count:
        raise BundleRefused(
            f"The image's system CA file {system} holds no certificate."
        )
    added = certificates(read(extra, "The extra CA bundle"), "The extra CA bundle")
    write(output, trusted.rstrip(b"\n") + b"\n" + "".join(added).encode())
    return count, len(added)


def main(argv):
    extra_only = argv[1:2] == ["--extra-only"]
    paths = argv[2:] if extra_only else argv[1:]
    if len(paths) != 2:
        print(
            "Usage: prepare_trust_bundle.py [--extra-only] EXTRA_BUNDLE OUTPUT",
            file=sys.stderr,
        )
        return 2
    try:
        if extra_only:
            added = build_extra_only(*paths)
        else:
            system, added = build(*paths)
    except BundleRefused as error:
        print(f"Keeplane can't use trust.extraCaBundle: {error}", file=sys.stderr)
        return 1
    if extra_only:
        print(f"Extra CAs written for the gateway: {added}.")
    else:
        print(f"System CAs kept: {system}. Extra CAs added: {added}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
