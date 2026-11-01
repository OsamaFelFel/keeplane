"""Copy private host credentials for the non-root local app without widening access."""

import os
import secrets
import shutil
import sys
from pathlib import Path

DATABASE = "keeplane.sqlite3"
# SQLite's files beside a database while it changes or after a crash.
JOURNALS = ("-journal", "-wal", "-shm")


def prepare_database_folder():
    """Give the app database its own folder in the account volume.

    The model enroller (ADR 027) mounts only this folder, read-only. Earlier
    previews kept the database at /state/keeplane.sqlite3: it gets a second
    name in the folder first, so an app still running from before keeps using
    the same file, and the earlier name is removed on a later start.
    """
    folder = Path("/state/database")
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    old, new = Path("/state") / DATABASE, folder / DATABASE
    if not old.exists():
        return
    if any(old.with_name(DATABASE + suffix).exists() for suffix in JOURNALS):
        raise RuntimeError(
            "The app database is in the middle of a change. Stop the app, then "
            "start the preview again."
        )
    if not new.exists():
        os.link(old, new)
    elif os.path.samefile(old, new) or old.stat().st_size == 0:
        # The same file under its earlier name, or an empty one an app from
        # before created after the move.
        old.unlink()
    else:
        raise RuntimeError(
            "Two app databases were found: /state/keeplane.sqlite3 and "
            "/state/database/keeplane.sqlite3. Keep the one you use and remove "
            "the other before starting the preview."
        )


def prepare():
    prepare_database_folder()
    for name in ("/state", "/provider-keys"):
        directory = Path(name)
        for path in (directory, *directory.rglob("*")):
            os.chown(path, 65532, 65532)
    Path("/provider-keys").chmod(0o700)
    signing_key = Path("/state/django-secret-key")
    if not signing_key.exists():
        signing_key.write_text(secrets.token_urlsafe(64) + "\n")
    signing_key.chmod(0o600)
    os.chown(signing_key, 65532, 65532)
    private_secrets = Path("/secrets")
    private_secrets.chmod(0o700)
    os.chown(private_secrets, 65532, 65532)
    for name in ("first-admin-password", "gateway-runtime-key", "gateway-admin-key"):
        destination = private_secrets / name
        shutil.copyfile(Path("/host-secrets") / name, destination)
        destination.chmod(0o600)
        os.chown(destination, 65532, 65532)


if __name__ == "__main__":
    try:
        prepare()
    except RuntimeError as error:
        # Shown by `docker compose logs account-volume-init`.
        print(error, file=sys.stderr)
        sys.exit(1)
