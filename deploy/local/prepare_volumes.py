"""Copy private host credentials for the non-root local app without widening access."""

import os
import secrets
import shutil
from pathlib import Path


def prepare():
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
    prepare()
