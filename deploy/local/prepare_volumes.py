"""Copy private host credentials for the non-root local app without widening access."""

import os
import secrets
import shutil
from pathlib import Path

# ADR 014: no migration from earlier previews. Their files stay where they
# were, untouched and unused, and start-up says so.
EARLIER_FILES = ("keeplane.sqlite3", "accounts.sqlite3", "model-approvals.sqlite3")
VOLUME = "keeplane-accounts-trial_model-approvals"
# The full reset, in order: stop this preview (with the enroller), remove every
# container still holding the account volume (an earlier preview's stopped
# containers in the old keeplane-accounts-trial project hold it too, and Docker
# refuses to remove a volume in use), then remove the volume.
RESET = (
    ("docker compose -f compose.yaml -f deploy/local/runtime.yaml --profile runtime "
     "down --remove-orphans"),
    f"docker ps -aq --filter volume={VOLUME} | xargs -r docker rm -f",
    f"docker volume rm {VOLUME}",
)


def earlier_database_notice(names):
    files = ", ".join("/state/" + name for name in names)
    stop, release, remove = RESET
    return (
        "Notice: this preview keeps its app database in /state/database. It doesn't "
        f"use or import the earlier preview files ({files}) and leaves them "
        f"unchanged. To reset the preview "
        f"fully, stop it with '{stop}', remove every container still using its account "
        f"volume, including the earlier keeplane-accounts-trial preview's stopped ones, "
        f"with '{release}', remove the volume with '{remove}', then start it again."
    )


def prepare_database_folder():
    """Give the app database its own folder: the model enroller (ADR 027)
    mounts only this folder of the account volume, read-only."""
    folder = Path("/state/database")
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    earlier = [name for name in EARLIER_FILES if (Path("/state") / name).exists()]
    if earlier:
        print(earlier_database_notice(earlier), flush=True)


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
    prepare()
