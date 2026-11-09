"""Work out a repo's Keeplane project from its Git folder (Spec 009 ST30, ADR 030).

Every clone of the same ``origin`` remote is one project: its ID is a UUIDv5 of
the remote's host and path, in lower case, without user names, passwords, port
or a ``.git`` ending. Its name is that path, as written in the remote. A repo
with no usable remote gets a random ID once, saved in its Git folder
(``.git/keeplane/project``), which Git never commits. The repo's top folder
name is then the project name, never its full local path.

Git is never run: a repo's own configuration could otherwise run commands.
The ID is the context the CLI asks for, not proof of where the code came from
(ADR 018).
"""

import json
import os
import re
import secrets
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

FILE_LIMIT = 1024 * 1024
NAME_LIMIT = 120
SAVED_FORMAT = "keeplane-project-v1"
REMOTE_SCHEMES = {"https", "http", "ssh", "git", "git+ssh", "ssh+git"}
# Fixed for good: changing it would give every repo a new project. It is
# uuid5(NAMESPACE_URL, "keeplane:project-identity:v1"), written out.
NAMESPACE = uuid.UUID("11b4916a-02a8-514d-b6ff-66bd26dee3af")

NOT_A_REPO = (
    "This folder isn't in a Git repo, so Keeplane can't tell which project "
    "it is. Run the command inside a repo, or pass --project and --name."
)
UNREADABLE = (
    "Keeplane can't read this repo's Git folder to work out its project. "
    "Check the folder, or pass --project and --name."
)


class ProjectIdentityError(Exception):
    pass


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    source: str  # "remote", "saved" or "given"


@dataclass(frozen=True)
class GitFolders:
    top: Path  # The working folder that holds ``.git``.
    git_dir: Path  # This checkout's own Git folder.
    common_dir: Path  # Shared by every worktree of the repo.


def _read(path, limit=FILE_LIMIT):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ProjectIdentityError(UNREADABLE)
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ProjectIdentityError(UNREADABLE)
    return raw.decode("utf-8")


def _pointer(path, prefix):
    """Follow a ``gitdir:`` or ``commondir`` file, relative to its folder."""
    text = _read(path, 4096).strip()
    if prefix:
        if not text.startswith(prefix):
            raise ProjectIdentityError(UNREADABLE)
        text = text[len(prefix) :].strip()
    if not text or "\n" in text or "\0" in text:
        raise ProjectIdentityError(UNREADABLE)
    target = Path(text)
    return (target if target.is_absolute() else path.parent / target).resolve()


def git_folders(directory):
    """Find the nearest checkout holding ``directory``: a repo, worktree or submodule."""
    start = Path(directory).expanduser().resolve()
    try:
        for folder in (start, *start.parents):
            marker = folder / ".git"
            if marker.is_symlink() or not marker.exists():
                continue
            # A worktree or submodule has a ``.git`` file that names its Git folder.
            git_dir = marker if marker.is_dir() else _pointer(marker, "gitdir:")
            if not (git_dir / "HEAD").is_file():
                raise ProjectIdentityError(UNREADABLE)
            common = git_dir / "commondir"
            common_dir = _pointer(common, "") if common.is_file() else git_dir
            if not common_dir.is_dir():
                raise ProjectIdentityError(UNREADABLE)
            return GitFolders(folder, git_dir, common_dir)
    except (OSError, UnicodeError):
        raise ProjectIdentityError(UNREADABLE) from None
    raise ProjectIdentityError(NOT_A_REPO)


ESCAPES = {"n": "\n", "t": "\t", "b": "\b", '"': '"', "\\": "\\"}


def _value(text):
    """A Git config value: quotes, escapes and comments as Git reads them."""
    result, quoted, pending = [], False, ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            result.append(pending + ESCAPES.get(text[index + 1], text[index + 1]))
            pending, index = "", index + 2
            continue
        if char == '"':
            result.append(pending)
            pending, quoted = "", not quoted
        elif not quoted and char in "#;":
            break
        elif not quoted and char in " \t":
            pending += char  # Kept only if more value follows.
        else:
            result.append(pending + char)
            pending = ""
        index += 1
    return "".join(result).strip() if not quoted else "".join(result + [pending])


HEADER = re.compile(r'\s*\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\](.*)')
KEY = re.compile(r"\s*([A-Za-z][A-Za-z0-9-]*)\s*(?:=(.*))?$")


def origin_url(common_dir):
    """The first ``remote.origin.url`` in the repo's own config, or None."""
    try:
        text = _read(Path(common_dir) / "config")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError):
        raise ProjectIdentityError(UNREADABLE) from None
    text = re.sub(r"\\\r?\n", "", text)  # Joined continuation lines.
    section = None
    for line in text.splitlines():
        header = HEADER.match(line)
        if header:
            name, sub, line = header.groups()
            name = name.lower()
            if sub is not None:
                sub = re.sub(r"\\(.)", r"\1", sub)
            elif "." in name:
                name, sub = name.split(".", 1)  # Old ``[remote.origin]`` form.
            section = (name, sub)
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue
        key = KEY.match(line)
        if key and section == ("remote", "origin") and key.group(1).lower() == "url":
            value = _value(key.group(2) or "")
            if value:
                return value
    return None


def remote_path(url):
    """``(host, path)`` of a network remote, or None for a local one.

    User names, passwords and ports are dropped, so SSH and HTTPS clones of
    one remote match.
    """
    url = url.strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    if "://" in url:
        parts = urlsplit(url)
        if parts.scheme.lower() not in REMOTE_SCHEMES:
            return None  # file:// and other local forms.
        try:
            host = parts.hostname
        except ValueError:
            return None
        path = parts.path
    else:
        # Git's short SSH form, ``[user@]host:path``: a colon before any slash.
        scp = re.fullmatch(r"(?:[^@/]*@)?(\[[^\]/]+\]|[^:/\[\]]+):(.*)", url)
        if scp is None or len(scp.group(1)) == 1:
            return None  # A local path, or a Windows drive letter.
        host, path = scp.group(1).strip("[]"), scp.group(2)
    if not host:
        return None
    path = re.sub(r"/+", "/", path).strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4].rstrip("/")
    if not path:
        return None
    return host.lower(), path


def remote_project(url):
    """The project every clone of ``url`` shares, or None for a local remote."""
    found = remote_path(url)
    if found is None:
        return None
    host, path = found
    project_id = uuid.uuid5(NAMESPACE, host + "/" + path.lower())
    return Project(str(project_id), display_name(path), "remote")


def display_name(text):
    """A printable project name the server accepts (at most 120 characters)."""
    name = "".join(c for c in text if c.isprintable()).strip()
    if len(name) > NAME_LIMIT:
        name = name[-NAME_LIMIT:].lstrip("/").strip()
    return name or "Unnamed repo"


def _decode_saved(raw):
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or set(data) != {"format", "id", "name"}
        or data["format"] != SAVED_FORMAT
        or not isinstance(data["name"], str)
        or data["id"] != str(uuid.UUID(data["id"]))
        or data["name"] != display_name(data["name"])
    ):
        raise ValueError
    return Project(data["id"], data["name"], "saved")


def saved_project(folders):
    """Read, or make once, the random ID of a repo with no remote."""
    folder = folders.common_dir / "keeplane"
    target = folder / "project"
    try:
        try:
            return _decode_saved(_read(target, 4096))
        except FileNotFoundError:
            pass
        try:
            folder.mkdir(mode=0o700)
        except FileExistsError:
            if folder.is_symlink() or not folder.is_dir():
                raise ProjectIdentityError(UNREADABLE) from None
        # The main checkout's folder name, so every worktree shares one name.
        top = (
            folders.common_dir.parent
            if folders.common_dir.name == ".git"
            else folders.top
        )
        payload = (
            json.dumps(
                {
                    "format": SAVED_FORMAT,
                    "id": str(uuid.uuid4()),
                    "name": display_name(top.name),
                }
            )
            + "\n"
        )
        pending = folder / (".pending-" + secrets.token_hex(8))
        descriptor = os.open(
            pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(pending, target)  # Never replaces an ID another run saved.
            except FileExistsError:
                pass
        finally:
            pending.unlink(missing_ok=True)
        return _decode_saved(_read(target, 4096))
    except ProjectIdentityError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ProjectIdentityError(UNREADABLE) from None


def identify(directory):
    """The project for the repo holding ``directory``."""
    folders = git_folders(directory)
    url = origin_url(folders.common_dir)
    found = remote_project(url) if url else None
    return found or saved_project(folders)


def resolve(directory, project_id=None, name=None):
    """Use ``--project`` and ``--name`` when given, the repo for anything left out."""
    if project_id is not None:
        try:
            project_id = str(uuid.UUID(str(project_id)))
        except (ValueError, TypeError, AttributeError):
            raise ProjectIdentityError(
                "Use a valid project UUID with --project."
            ) from None
    if project_id is not None and name is not None:
        return Project(project_id, name, "given")
    found = identify(directory)
    return Project(
        project_id or found.id,
        found.name if name is None else name,
        "given" if project_id else found.source,
    )
