"""Opt-in private runtime history; no vendor profiles or stored credentials."""

import argparse
import fcntl
import json
import os
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

FORMAT = "keeplane-opencode-session-v1"
FILES = {"binding.json", "lock", "runtime.db", "runtime.db-wal", "runtime.db-shm"}


def private_file(info):
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o600
    )


@contextmanager
def locked(path):
    root = Path(path).expanduser()
    root = root.parent.resolve(strict=True) / root.name
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        pass
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = None
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError(
                "Session directory must be private and owned by this user."
            )
        names = set(os.listdir(directory))
        if names - FILES or (names and "binding.json" not in names):
            raise ValueError("Refusing existing or incomplete runtime state.")
        lock = os.open(
            "lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=directory,
        )
        if not private_file(os.fstat(lock)):
            raise ValueError("Session lock must be a private owned regular file.")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Session state is already in use.") from None
        yield root, directory, lock, set(os.listdir(directory)) - {"lock"}
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def marker(directory):
    descriptor = os.open(
        "binding.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    with os.fdopen(descriptor, "rb") as source:
        if not private_file(os.fstat(source.fileno())):
            raise ValueError("Session binding is unavailable.")
        raw = source.read(4097)
    if len(raw) > 4096:
        raise ValueError("Session binding is unavailable.")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"format", "binding"}
        or value["format"] != FORMAT
        or not isinstance(value["binding"], dict)
        or set(value["binding"]) != {"directory", "gateway", "model", "version"}
        or any(
            not isinstance(item, str) or not item for item in value["binding"].values()
        )
    ):
        raise ValueError("Session binding is unavailable.")
    return value["binding"]


def check(root, directory, session=None, binding=None):
    names = set(os.listdir(directory))
    if names - FILES or any(
        not private_file(os.stat(name, dir_fd=directory, follow_symlinks=False))
        for name in names
    ):
        raise ValueError("Unexpected or unsafe session files.")
    database = root / "runtime.db"
    if not database.exists():
        raise ValueError("Session database is unavailable.")
    if database.stat().st_size == 0:
        return  # A new state or a failed version probe has no native schema yet.
    try:
        with closing(
            sqlite3.connect(
                "file:" + quote(str(database)) + "?mode=ro", uri=True, timeout=1
            )
        ) as connection:
            if connection.execute(
                "SELECT EXISTS(SELECT 1 FROM credential LIMIT 1)"
            ).fetchone()[0]:
                raise ValueError(
                    "Session state contains credentials; refusing to import them."
                )
            if session is not None:
                row = connection.execute(
                    "SELECT directory, model, time_idle, time_suspended "
                    "FROM session_v2 WHERE id = ?",
                    [session],
                ).fetchone()
                model = json.loads(row[1]) if row and row[1] else {}
                if (
                    not row
                    or row[0] != binding["directory"]
                    or model != {"providerID": "keeplane", "id": binding["model"]}
                    or row[2] is None
                    or row[3] is not None
                ):
                    raise ValueError(
                        "Choose an existing idle session in this directory and model."
                    )
    except sqlite3.Error:
        raise ValueError("Session database is unavailable.") from None


@contextmanager
def managed(path, binding, session):
    if path is None:
        if session is not None:
            raise ValueError("Choose --state-dir when resuming a session.")
        yield None
        return
    payload = json.dumps({"format": FORMAT, "binding": binding}).encode()
    if len(payload) > 4096:
        raise ValueError("Session binding exceeds the supported size.")
    root = Path(path).expanduser().absolute()
    root = root.parent.resolve(strict=True) / root.name
    if root.is_relative_to(Path(binding["directory"])):
        raise ValueError("Keep session state outside the working repository.")
    if session is not None and not (root / "binding.json").exists():
        raise ValueError("Cannot resume an empty session directory.")
    with locked(root) as (root, directory, lock, names):
        if not names:
            if session is not None:
                raise ValueError("Cannot resume an empty session directory.")
            for name, data in (
                ("runtime.db", b""),
                (
                    "binding.json",
                    payload,
                ),
            ):
                descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                with os.fdopen(descriptor, "wb") as target:
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
            os.fsync(directory)
        elif marker(directory) != binding:
            raise ValueError(
                "Session directory, gateway, model or runtime version changed."
            )
        check(root, directory, session, binding)
        if session is not None and (root / "runtime.db").stat().st_size == 0:
            raise ValueError("Cannot resume an empty session directory.")
        yield SimpleNamespace(database=str(root / "runtime.db"), lock=lock)
        check(root, directory)


def discard(path):
    if not (Path(path).expanduser() / "binding.json").is_file():
        raise ValueError("Choose an existing Keeplane session directory.")
    with locked(path) as (_root, directory, _, names):
        if not names:
            raise ValueError("Choose an existing Keeplane session directory.")
        marker(directory)
        if set(os.listdir(directory)) - FILES:
            raise ValueError("Unexpected session files; inspect them before removal.")
        for name in os.listdir(directory):
            if not private_file(os.stat(name, dir_fd=directory, follow_symlinks=False)):
                raise ValueError("Unsafe session file; inspect it before removal.")
        for name in os.listdir(directory):
            if name not in {"lock", "binding.json"}:
                os.unlink(name, dir_fd=directory)
        # Keep the stable lock inode and binding. A concurrent future invocation
        # starts a new history only after this locked reset completes.
        descriptor = os.open(
            "runtime.db",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        os.close(descriptor)
        os.fsync(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discard", required=True, type=Path)
    args = parser.parse_args()
    try:
        discard(args.discard)
    except (OSError, ValueError):
        parser.exit(
            1,
            "Cannot discard this session state safely; inspect it or wait for the active turn.\n",
        )
    print("Removed local session history.")
