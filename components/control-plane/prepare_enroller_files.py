"""Give one gateway copy's model enroller only its own credentials (ADR 027).

Runs in Kubernetes as the init container of each managed gateway copy Pod, as
the app user, before the enroller starts. The gateway Pod has no fsGroup (it
shares the provider-key volume), so Secret files mounted there could be read
only by root. The credentials arrive instead as environment values from
secretKeyRef, in this init container only, and it writes the ones this copy
needs into a private in-memory folder that only the enroller container mounts:

- the approvals role's password, and this copy's status role and password,
  picked by the Pod's own name, so an enroller never holds another copy's
  status password;
- the gateway admin and runtime keys and the database CA certificate;
- a random signing secret of its own: the enroller signs nothing, and never
  gets the app's shared signing secret.

It also makes the Pod-local guard folder private to the app user, as the
Docker preview's runtime preparation does. It writes nothing else there.
"""

import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path

FILES = Path("/run/keeplane-enroller/files")
GUARD = Path("/guard/installed")
ROLE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
KEY = re.compile(r"[A-Za-z0-9_-]{32,256}")
INDEX = re.compile(r"0|[1-9][0-9]?")
CERTIFICATE = "-----BEGIN CERTIFICATE-----"
MAX_SECRET = 4096
MAX_CA = 262144
PREFIX = "KEEPLANE_ENROLLER_"


class Unprepared(ValueError):
    """A setting is missing or unsafe; the message never holds a secret."""


def copy_index(pod, prefix, copies):
    """This copy's number from its StatefulSet Pod name, such as keeplane-gateway-1."""
    if not prefix or not pod.startswith(prefix):
        raise Unprepared("This Pod is not one of the gateway copies")
    number = pod[len(prefix) :]
    if not INDEX.fullmatch(number) or int(number) >= copies:
        raise Unprepared("This Pod is not one of the gateway copies")
    return int(number)


def text(environ, name, limit=MAX_SECRET):
    value = environ.get(name, "").strip()
    if not value or len(value) > limit or "\x00" in value:
        raise Unprepared(f"{name} is missing or not usable")
    return value


def plan(environ):
    """Every file the enroller gets, by name, from the init container's settings."""
    roles = [
        role.strip() for role in environ.get(PREFIX + "STATUS_ROLES", "").split(",")
    ]
    if not roles or not all(ROLE.fullmatch(role) for role in roles):
        raise Unprepared("Each gateway copy needs a lowercase status role name")
    if len(set(roles)) != len(roles):
        raise Unprepared("Each gateway copy needs its own status role")
    index = copy_index(
        environ.get("KEEPLANE_GATEWAY_COPY", ""),
        environ.get(PREFIX + "COPY_PREFIX", ""),
        len(roles),
    )
    keys = {}
    for name in ("GATEWAY_ADMIN_KEY", "GATEWAY_RUNTIME_KEY"):
        value = text(environ, PREFIX + name)
        if not KEY.fullmatch(value):
            raise Unprepared(f"{PREFIX + name} is not a valid gateway key")
        keys[name.lower().replace("_", "-")] = value
    ca = text(environ, PREFIX + "DATABASE_CA", MAX_CA)
    if CERTIFICATE not in ca:
        raise Unprepared(f"{PREFIX}DATABASE_CA is not a PEM certificate")
    approvals = text(environ, PREFIX + "APPROVALS_PASSWORD")
    status = text(environ, f"{PREFIX}STATUS_PASSWORD_{index}")
    if approvals == status:
        raise Unprepared(
            "The approvals role and the status role need different passwords"
        )
    return {
        "approvals-password": approvals,
        "status-user": roles[index],
        "status-password": status,
        "database-ca.crt": ca,
        **keys,
        "signing-secret": secrets.token_urlsafe(64),
    }


def private_directory(path):
    """Create or reuse a folder only this user can open."""
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise Unprepared(f"{path} is not a private folder")
    path.chmod(0o700)


def write_private(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".enroller-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(value + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o400)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare(environ, files=FILES, guard=GUARD):
    contents = plan(environ)
    private_directory(files)
    for name, value in contents.items():
        write_private(files / name, value)
    private_directory(guard)
    return contents["status-user"]


if __name__ == "__main__":
    try:
        role = prepare(os.environ)
    except Unprepared as error:
        sys.exit(f"The model enroller's files were not prepared: {error}.")
    except OSError:
        sys.exit(
            "The model enroller's files were not prepared: a folder is not writable."
        )
    print(f"The model enroller's files are ready; its status role is {role}.")
