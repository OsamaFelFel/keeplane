"""Private, explicit CLI credentials; no vendor configuration or history import."""

import fcntl
import json
import os
import re
import secrets
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .server_connection import ConnectionError, origin
else:
    from server_connection import ConnectionError, origin


class ProfileError(Exception):
    pass


@dataclass(repr=False, frozen=True)
class Credential:
    issuer: str
    actor_id: str
    access_token: str
    refresh_token: str
    client_id: str = "keeplane-cli"

    def __repr__(self):
        return "<Keeplane credential: redacted>"


def private_file(info):
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o600
    )


def decode(data):
    try:
        fields = {"format", "issuer", "actor_id", "access_token", "refresh_token"}
        if isinstance(data, dict) and data.get("format") == "keeplane-credential-v1":
            if set(data) != fields:
                raise ValueError
            data = dict(data, client_id="keeplane-cli")
        elif (
            not isinstance(data, dict)
            or data.get("format") != "keeplane-credential-v2"
            or set(data) != fields | {"client_id"}
        ):
            raise ValueError
        if (
            data["client_id"] not in {"keeplane-cli", "keeplane-cli-device"}
            or data["issuer"] != origin(data["issuer"])
            or data["actor_id"] != str(uuid.UUID(data["actor_id"]))
            or not isinstance(data["access_token"], str)
            or not re.fullmatch(r"kpc_[A-Za-z0-9_-]{43}", data["access_token"])
            or not isinstance(data["refresh_token"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", data["refresh_token"])
        ):
            raise ValueError
        return Credential(**{key: data[key] for key in Credential.__annotations__})
    except (ValueError, TypeError, AttributeError, ConnectionError):
        raise ProfileError("Credential profile is invalid.") from None


def unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError
        result[name] = value
    return result


class Profile:
    def __init__(self, directory):
        self.directory = directory

    def load(self):
        descriptor = os.open(
            "credential.json",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=self.directory,
        )
        with os.fdopen(descriptor, "rb") as source:
            if not private_file(os.fstat(source.fileno())):
                raise ProfileError(
                    "Credential file must be private and owned by this user."
                )
            raw = source.read(4097)
        if len(raw) > 4096:
            raise ProfileError("Credential profile is invalid.")
        try:
            return decode(json.loads(raw, object_pairs_hook=unique))
        except (ValueError, RecursionError):
            raise ProfileError("Credential profile is invalid.") from None

    def save(self, credential):
        data = dict(format="keeplane-credential-v2", **vars(credential))
        decode(data)
        payload = json.dumps(data).encode()
        if len(payload) > 4096:
            raise ProfileError("Credential profile is invalid.")
        name = ".pending-" + secrets.token_hex(16)
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            os.replace(
                name,
                "credential.json",
                src_dir_fd=self.directory,
                dst_dir_fd=self.directory,
            )
            os.fsync(self.directory)
        finally:
            try:
                os.unlink(name, dir_fd=self.directory)
            except FileNotFoundError:
                pass

    def forget(self):
        self.load()  # Refuse to remove foreign or malformed state.
        os.unlink("credential.json", dir_fd=self.directory)
        os.fsync(self.directory)


@contextmanager
def opened(path, *, create=False):
    directory = lock = None
    try:
        root = Path(path).expanduser().absolute()
        root = root.parent.resolve(strict=True) / root.name
        if create:
            try:
                root.mkdir(mode=0o700)
            except FileExistsError:
                pass
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ProfileError(
                "Credential directory must be private and owned by this user."
            )
        if set(os.listdir(directory)) - {"credential.json", "lock"}:
            raise ProfileError("Refusing foreign or incomplete credential state.")
        for name in os.listdir(directory):
            if not private_file(os.stat(name, dir_fd=directory, follow_symlinks=False)):
                raise ProfileError("Credential state contains an unsafe file.")
        lock = os.open(
            "lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=directory,
        )
        if not private_file(os.fstat(lock)):
            raise ProfileError("Credential lock is unsafe.")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProfileError("Credential profile is already in use.") from None
        yield Profile(directory)
    except OSError:
        raise ProfileError(
            "Credential profile is unavailable; check its private storage."
        ) from None
    finally:
        if lock is not None:
            os.close(lock)
        if directory is not None:
            os.close(directory)
