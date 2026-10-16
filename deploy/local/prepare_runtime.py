"""Prepare disabled operator enrollment before a fresh managed gateway starts."""

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path

ROOT = Path("/installed")


def write_private(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=".runtime-", dir=path.parent)
    try:
        os.fchown(descriptor, 65532, 65532)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def key(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("A private credential file is required")
        value = source.read(259).strip()
    if not re.fullmatch(rb"[A-Za-z0-9_-]{32,256}", value):
        raise ValueError("A valid private credential is required")
    return value


def prepare():
    if not stat.S_ISDIR(ROOT.lstat().st_mode):
        raise ValueError("The private installation volume is required")
    ROOT.chmod(0o700)
    os.chown(ROOT, 65532, 65532)
    write_private(ROOT / "manifest.json", b'{"version":2,"enabled":false}')
    callback = ROOT / "callback-key"
    if callback.exists() or callback.is_symlink():
        key(callback)
    else:
        write_private(callback, secrets.token_urlsafe(32).encode())
    template = Path("/runtime-base.json").read_text()
    for name in ("admin", "runtime"):
        value = key(Path("/run/secrets") / ("gateway-" + name + "-key"))
        template = template.replace(
            "${GATEWAY_" + name.upper() + "_KEY_HASH}",
            "sha256:" + hashlib.sha256(value).hexdigest(),
        )
    value = json.loads(template)
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    write_private(ROOT / "trusted.json", raw)
    write_private(ROOT / "gateway.json", raw)


if __name__ == "__main__":
    try:
        prepare()
    except (OSError, ValueError, TypeError):
        raise SystemExit(
            "Runtime preparation did not complete; keep the managed gateway stopped."
        ) from None
