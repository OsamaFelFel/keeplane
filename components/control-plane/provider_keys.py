"""File-backed shared provider keys for the protected local gateway trial."""

import os
from pathlib import Path
import re
import uuid


KEY_NAME = re.compile(r"key-[0-9a-f]{32}")


def save(directory, value):
    if not isinstance(value, str) or not 12 <= len(value) <= 512 or "\n" in value or "\r" in value:
        raise ValueError("Enter a valid shared provider key")
    if not directory:
        raise OSError("Provider key storage is not configured")
    root = Path(directory)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / ("key-" + uuid.uuid4().hex)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as secret:
            secret.write(value)
            secret.flush()
            os.fsync(secret.fileno())
            os.fchown(secret.fileno(), 65532, 65532)
        return str(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def remove(directory, path):
    if not is_managed(directory, path):
        return False
    target = Path(path)
    try:
        target.unlink()
        return True
    except OSError:
        return False


def from_resource(resource):
    value = resource.get("auth", {}).get("key", {}).get("value")
    return value.get("file") if isinstance(value, dict) else None


def is_managed(directory, path):
    return bool(directory and isinstance(path, str) and
                Path(path).parent == Path(directory) and KEY_NAME.fullmatch(Path(path).name))
