"""Repair only managed provider-key permissions before the app starts."""

import os
import re
import stat

KEY_NAME = re.compile(r"key-[0-9a-f]{32}")


def prepare(directory, *, uid=65532, gid=65532):
    root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        entries = []
        for name in os.listdir(root):
            if not KEY_NAME.fullmatch(name):
                continue
            try:
                info = os.stat(name, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                continue  # A running owner may have removed its old key.
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid not in (0, uid)
            ):
                raise ValueError("Provider-key storage contains an unsafe entry")
            entries.append((name, info.st_dev, info.st_ino))
        for name, device, inode in entries:
            try:
                key = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root
                )
            except FileNotFoundError:
                continue
            try:
                info = os.fstat(key)
                if (
                    (info.st_dev, info.st_ino) != (device, inode)
                    or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid not in (0, uid)
                ):
                    raise ValueError("Provider-key storage changed during preparation")
                os.fchown(key, uid, gid)
                os.fchmod(key, 0o600)
            finally:
                os.close(key)
        os.fchown(root, uid, gid)
        os.fchmod(root, 0o700)
    finally:
        os.close(root)


if __name__ == "__main__":
    try:
        prepare("/provider-keys")
    except (OSError, ValueError):
        raise SystemExit("Provider-key permissions could not be prepared.") from None
    print("Provider-key storage is ready.")
