"""Copy private host credentials for the non-root local app without widening access."""

import os
import shutil
from pathlib import Path


def prepare():
    for name in ("/state", "/provider-keys"):
        directory = Path(name)
        for path in (directory, *directory.rglob("*")):
            os.chown(path, 65532, 65532)
    secrets = Path("/secrets")
    secrets.chmod(0o700)
    os.chown(secrets, 65532, 65532)
    for name in ("first-admin-password", "gateway-runtime-key", "gateway-admin-key"):
        destination = secrets / name
        shutil.copyfile(Path("/host-secrets") / name, destination)
        destination.chmod(0o600)
        os.chown(destination, 65532, 65532)


if __name__ == "__main__":
    prepare()
