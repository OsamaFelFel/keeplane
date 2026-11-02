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

It also installs Keeplane's protected runtime in the Pod-local guard folder,
private to the app user, as the Docker preview's runtime preparation
(deploy/local/prepare_runtime.py) does, before the gateway container starts
from it:

- a disabled declaration (manifest.json), written first, so no protected call
  is admitted until the enroller has read its guard back;
- the callback key the copy's protected checks send to the app, from the
  installer's gateway keys Secret, the same for every copy and the app;
- the trusted base (trusted.json) and the gateway's starting configuration
  (gateway.json): the chart's rendered gateway configuration with its key-hash
  variables written out, byte for byte the same in both files.

What an earlier start of this Pod left there (the record of served models and
any candidate declaration) is removed: the gateway starts afresh with the Pod,
so no request can still hold an older guard. The enroller's first pass then
enrols the saved models from that fresh base (ADR 027).
"""

import json
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
# The trusted base arrives as one environment value. Linux refuses to start a
# process with a single value over 128 KiB (MAX_ARG_STRLEN), name included, so
# the chart refuses a larger base with the same limit (_enroller.tpl).
MAX_BASE = 122880
HASH = re.compile(r"sha256:[0-9a-f]{64}")
# The key-hash variables the managed gateway's key policies may name; the
# chart refuses any other key policy. The first two are always there.
HASH_VARIABLES = (
    "GATEWAY_ADMIN_KEY_HASH",
    "GATEWAY_RUNTIME_KEY_HASH",
    "GATEWAY_ADMIN_KEY_HASH_NEXT",
    "GATEWAY_RUNTIME_KEY_HASH_NEXT",
)
REQUIRED_HASHES = HASH_VARIABLES[:2]
ADMIN_ADDRESS = "127.0.0.1:15000"
DISABLED = b'{"enabled":false,"version":2}'
STALE = ("served.json", "candidate.json")


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


def runtime_plan(environ):
    """The protected runtime's starting files, by name, in writing order.

    The base is the chart's rendered gateway configuration. Only its key-hash
    variables are written out, from the gateway keys Secret, as in the Docker
    preview. Any other variable, such as the gateway database password, stays
    for the gateway to read from its own environment, so no other credential
    reaches the guard folder.
    """
    callback = text(environ, PREFIX + "CALLBACK_KEY")
    if not KEY.fullmatch(callback):
        raise Unprepared(f"{PREFIX}CALLBACK_KEY is not a valid callback key")
    raw = environ.get(PREFIX + "RUNTIME_BASE", "")
    if len(raw.encode("utf-8", "surrogateescape")) > MAX_BASE:
        raise Unprepared(
            f"{PREFIX}RUNTIME_BASE is over {MAX_BASE} bytes (120 KiB), the most the "
            "chart passes as one environment value; shorten the gateway configuration"
        )
    template = text(environ, PREFIX + "RUNTIME_BASE", MAX_BASE)
    for name in HASH_VARIABLES:
        setting = PREFIX + name
        if setting not in environ and name not in REQUIRED_HASHES:
            continue
        value = text(environ, setting)
        if not HASH.fullmatch(value):
            raise Unprepared(f"{setting} is not a sha256 key hash")
        template = template.replace("${" + name + "}", value)
    # Only the key-hash variables are this step's: another variable, even one
    # named GATEWAY_*, such as a database password, is the gateway's to read.
    if any("${" + name + "}" in template for name in HASH_VARIABLES):
        raise Unprepared(
            "The gateway configuration names a key hash this copy was not given"
        )
    try:
        base = json.loads(template)
    except (ValueError, RecursionError):
        raise Unprepared(f"{PREFIX}RUNTIME_BASE is not JSON") from None
    if not isinstance(base, dict) or not isinstance(base.get("config"), dict):
        raise Unprepared(f"{PREFIX}RUNTIME_BASE is not a gateway configuration")
    if base["config"].get("adminAddr") != ADMIN_ADDRESS:
        raise Unprepared("The gateway's admin address must stay on loopback")
    trusted = json.dumps(
        base, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    # The disabled declaration goes first: nothing is admitted until the
    # enroller reads its guard back.
    return {
        "manifest.json": DISABLED,
        "callback-key": callback.encode("ascii"),
        "trusted.json": trusted,
        "gateway.json": trusted,
    }


def write_runtime(path, value):
    """Replace one runtime file, mode 0600 as the enroller writes them."""
    descriptor, temporary = tempfile.mkstemp(prefix=".runtime-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install_runtime(runtime, guard):
    """Write the protected runtime's starting files into the guard folder."""
    private_directory(guard)
    for name, value in runtime.items():
        write_runtime(guard / name, value)
        if name == "manifest.json":
            # A fresh gateway serves no model yet: forget an earlier start's.
            for stale in STALE:
                (guard / stale).unlink(missing_ok=True)


def prepare(environ, files=FILES, guard=GUARD):
    contents = plan(environ)
    private_directory(files)
    for name, value in contents.items():
        write_private(files / name, value)
    private_directory(guard)
    return contents["status-user"]


def prepare_copy(environ, files=FILES, guard=GUARD):
    """The enroller's files and the protected runtime, all checked before any write."""
    runtime = runtime_plan(environ)
    role = prepare(environ, files, guard)
    install_runtime(runtime, guard)
    return role


if __name__ == "__main__":
    try:
        role = prepare_copy(os.environ)
    except Unprepared as error:
        sys.exit(
            "The model enroller's files and protected runtime were not prepared: "
            f"{error}."
        )
    except OSError:
        sys.exit(
            "The model enroller's files and protected runtime were not prepared: "
            "a folder is not writable."
        )
    print(
        "The model enroller's files and the protected runtime are ready; "
        f"its status role is {role}."
    )
