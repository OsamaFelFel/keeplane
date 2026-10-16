"""Read a private managed credential only for a trusted server consumer."""

import os
import stat
from pathlib import Path

from common.errors import StorageUnavailable
from integrations.gateway.keys import KEY_NAME

from .provider_key_http import valid_personal_key


class ResolvedProviderKey:
    __slots__ = ("_value",)

    def __init__(self, value):
        self._value = value

    def __repr__(self):
        return "ResolvedProviderKey(<redacted>)"

    __str__ = __repr__

    def for_provider(self):
        """Plaintext for trusted transport only. Never serialize or log this value."""
        return self._value


def read_private_key(directory, name):
    try:
        directory = Path(directory)
        if not directory.is_absolute() or not KEY_NAME.fullmatch(name):
            raise ValueError
        root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(root)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) not in (
                0o500,
                0o700,
            ):
                raise ValueError
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root
            )
            try:
                info = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) not in (0o400, 0o600)
                    or not 12 <= info.st_size <= 512
                ):
                    raise ValueError
                raw = os.read(descriptor, 513)
                value = raw.decode("ascii")
                if len(raw) != info.st_size or not valid_personal_key(value):
                    raise ValueError
                return ResolvedProviderKey(value)
            finally:
                os.close(descriptor)
        finally:
            os.close(root)
    except (OSError, ValueError, TypeError, UnicodeError):
        raise StorageUnavailable("Provider key is unavailable") from None
