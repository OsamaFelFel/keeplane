"""Copy one reviewed root instruction file; never replace existing guidance."""

import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

if __package__:
    from . import migration_preview
    from .instructions import LIMIT
else:
    import migration_preview
    from instructions import LIMIT


SOURCES = {"CLAUDE.md", "QWEN.md"}
TARGET = "AGENTS.md"


class MigrationError(ValueError):
    pass


def _directory(path):
    if os.name != "posix":
        raise MigrationError("Migration supports macOS and Linux.")
    path = Path(path).expanduser()
    if path.is_symlink():
        raise MigrationError("Choose a directory without a symlink.")
    path = path.resolve(strict=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        os.close(descriptor)
        raise MigrationError("Use a directory you own without group or public write access.")
    return path, descriptor


def _read(descriptor, name, *, private=False, limit=LIMIT):
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    with os.fdopen(source, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise MigrationError("Use owned regular files without hardlinks or symlinks.")
        if private and info.st_mode & 0o077:
            raise MigrationError("The saved plan must be private to your OS user.")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > limit or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise MigrationError("A file changed while reading or exceeds its size limit.")
        return raw


def _current(descriptor, *, target_absent=True):
    names = set(os.listdir(descriptor))
    if target_absent and TARGET in names:
        raise MigrationError("AGENTS.md already exists; nothing will replace it.")
    contents, hashes = {}, {}
    for name in sorted(SOURCES & names):
        raw = _read(descriptor, name)
        text = raw.decode("utf-8")
        if not text.strip() or "\0" in text:
            raise MigrationError("Instructions must contain nonempty UTF-8 text without NUL bytes.")
        contents[name] = raw
        hashes[name] = hashlib.sha256(raw).hexdigest()
    if len(set(hashes.values())) > 1:
        raise MigrationError("Root instructions conflict; review them before creating a plan.")
    return hashes, contents


def _plan_location(root, path):
    path = Path(path).expanduser()
    parent, descriptor = _directory(path.parent)
    if (parent / path.name).is_relative_to(root):
        os.close(descriptor)
        raise MigrationError("Save the plan outside the repository.")
    return path.name, descriptor


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise MigrationError("The saved plan contains duplicate fields.")
        result[key] = value
    return result


def _validated(raw, root):
    plan = json.loads(raw, object_pairs_hook=_pairs)
    if (
        not isinstance(plan, dict)
        or set(plan) != {"version", "directory", "source", "target", "sources"}
        or type(plan["version"]) is not int or plan["version"] != 1
        or plan["directory"] != str(root) or plan["target"] != TARGET
        or not isinstance(plan["source"], str) or plan["source"] not in SOURCES
        or not isinstance(plan["sources"], dict)
        or not set(plan["sources"]) <= SOURCES
        or plan["source"] not in plan["sources"]
        or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
               for value in plan["sources"].values())
        or len(set(plan["sources"].values())) != 1
    ):
        raise MigrationError("The saved plan is invalid or belongs to a different repository.")
    return plan


def review(directory, source, plan_path):
    if source not in SOURCES:
        raise MigrationError("Choose root CLAUDE.md or QWEN.md explicitly.")
    inventory = migration_preview.preview(directory)
    if any(row["status"] == "blocked" for row in inventory["inventory"]) or any(
        row["kind"] == "unreadable-directory" for row in inventory["findings"]
    ):
        raise MigrationError("Resolve blocked preview sources before saving a migration plan.")
    root, descriptor = _directory(directory)
    try:
        hashes, _ = _current(descriptor)
        if source not in hashes:
            raise MigrationError("The selected instruction file is missing.")
        reviewed = {row["source"]: row.get("sha256") for row in inventory["inventory"]
                    if row["source"] in SOURCES}
        if reviewed != hashes:
            raise MigrationError("Instructions changed during preview; run it again.")
        plan = {"version": 1, "directory": str(root), "source": source,
                "target": TARGET, "sources": hashes}
        encoded = json.dumps(plan, indent=2).encode("utf-8")
        if len(encoded) > 4096:
            raise MigrationError("The migration plan exceeds its 4 KiB limit.")
        name, parent = _plan_location(root, plan_path)
        created_plan = False
        try:
            output = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
            created_plan = True
            with os.fdopen(output, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent)
        except BaseException:
            if created_plan:
                raise MigrationError("The plan was not confirmed saved; inspect it and save a fresh plan before applying.") from None
            raise
        finally:
            os.close(parent)
        return {**inventory, "plan": {"source": source, "target": TARGET,
                                      "file": str(Path(plan_path).expanduser().absolute())}}
    finally:
        os.close(descriptor)


def _remove_temporary(descriptor, name, identity):
    try:
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (info.st_dev, info.st_ino) != identity or not stat.S_ISREG(info.st_mode):
        raise MigrationError("Migration recovery requires review; a temporary path changed.")
    os.unlink(name, dir_fd=descriptor)


def _check_target(descriptor, identity, raw):
    file = os.open(TARGET, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    with os.fdopen(file, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            (info.st_dev, info.st_ino) != identity
            or not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or stream.read(LIMIT + 1) != raw
        ):
            raise MigrationError("The created target changed; inspect it before continuing.")


def apply(directory, plan_path):
    root, descriptor = _directory(directory)
    temporary, identity, raw = None, None, None
    created = False
    try:
        if root == Path.home().resolve() or ".git" not in os.listdir(descriptor):
            raise MigrationError("Choose the repository root containing .git.")
        name, parent = _plan_location(root, plan_path)
        try:
            plan = _validated(_read(parent, name, private=True, limit=4096), root)
        finally:
            os.close(parent)
        hashes, contents = _current(descriptor)
        if hashes != plan["sources"]:
            raise MigrationError("Instructions changed since preview; create a new plan.")
        raw = contents[plan["source"]]
        temporary = ".keeplane-init-" + uuid.uuid4().hex + ".pending"
        output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=descriptor)
        with os.fdopen(output, "wb") as stream:
            info = os.fstat(stream.fileno())
            identity = (info.st_dev, info.st_ino)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            if _current(descriptor)[0] != hashes:
                raise MigrationError("Instructions changed before apply; create a new plan.")
            os.link(temporary, TARGET, src_dir_fd=descriptor, dst_dir_fd=descriptor,
                    follow_symlinks=False)
            created = True
            _check_target(descriptor, identity, raw)
            if _current(descriptor, target_absent=False)[0] != hashes:
                raise MigrationError("Instructions changed during apply; create a new plan.")
            os.unlink(temporary, dir_fd=descriptor)
            temporary = None
            os.fsync(descriptor)
        return {"mode": "partial-instruction-migration", "source": plan["source"],
                "created": TARGET, "sha256": hashes[plan["source"]], "originals": "kept"}
    except BaseException:
        cleanup_failed = False
        if identity is not None and temporary:
            try:
                _remove_temporary(descriptor, temporary, identity)
                os.fsync(descriptor)
            except (OSError, MigrationError):
                cleanup_failed = True
        if created or cleanup_failed:
            # POSIX cannot atomically unlink only a particular inode. Never
            # risk removing a human's edit/replacement of the published path.
            raise MigrationError(
                "Migration outcome needs review. Inspect AGENTS.md and .keeplane-init-*.pending; originals were not changed by Keeplane."
            ) from None
        raise
    finally:
        os.close(descriptor)
