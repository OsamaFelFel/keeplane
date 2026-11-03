"""Unreadable-file checks that still mean something when the suite runs as root.

Root reads a file whatever its mode, so `chmod(0)` cannot make a file
unreadable for root. The real mode-0 case therefore runs only as a non-root
user and is reported as skipped (never passed) under root. The forced case
runs for every user: it makes the operating system's file-open call refuse
one exact file with the same `PermissionError` (EACCES) a non-root user gets,
at the same call the product code uses. Every other open is unchanged.
"""

import errno
import os

import pytest

RUNNING_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0

ROOT_SKIP_REASON = (
    "running as root: root can read a mode-0 file, so a real unreadable file "
    "cannot be made; the forced read-denial case covers the same refusal"
)

skip_as_root = pytest.mark.skipif(RUNNING_AS_ROOT, reason=ROOT_SKIP_REASON)


def deny_read(monkeypatch, path):
    """Make every `os.open` of this exact file fail as a permission denial.

    The file is matched by device and inode, so a relative name opened
    through a directory descriptor (`dir_fd`) is refused as well as an
    absolute path. Opens of any other file go to the real `os.open`.
    """
    target = os.stat(path, follow_symlinks=False)
    denied = (target.st_dev, target.st_ino)
    real_open = os.open

    def guarded_open(file, flags, mode=0o777, *, dir_fd=None):
        try:
            found = os.stat(file, dir_fd=dir_fd, follow_symlinks=False)
        except (OSError, TypeError, ValueError):
            found = None
        if found is not None and (found.st_dev, found.st_ino) == denied:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), file)
        return real_open(file, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", guarded_open)
