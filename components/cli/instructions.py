"""Snapshot explicitly selected instruction text; never execute repo config."""

import hashlib
import os
import stat
from pathlib import Path

LIMIT = 32768


def snapshot(directory, sources):
    if len(sources) > 8:
        raise ValueError("Choose at most eight instruction files.")
    root, result, total = Path(directory), [], 0
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for source in sources:
            path = Path(source).expanduser()
            if not path.is_absolute():
                path = root / path
            if path.parent != root or any(row["path"] == path.name for row in result):
                raise ValueError(
                    "Choose distinct instruction files directly in the working directory."
                )
            file = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=descriptor,
            )
            with os.fdopen(file, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Instructions must be regular files.")
                raw = stream.read(LIMIT + 1)
            total += len(raw)
            if len(raw) > LIMIT or total > 2 * LIMIT:
                raise ValueError("Instructions exceed 32 KiB per file or 64 KiB total.")
            content = raw.decode("utf-8")
            if not content.strip() or "\0" in content:
                raise ValueError(
                    "Instructions must contain nonempty UTF-8 text without NUL bytes."
                )
            result.append(
                {
                    "path": path.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "content": content,
                }
            )
    except (OSError, UnicodeError):
        raise ValueError("Cannot read the selected instruction file safely.") from None
    finally:
        os.close(descriptor)
    return {"directory": str(root), "sources": result}
