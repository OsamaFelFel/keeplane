"""The developer's Keeplane CLI settings file, kept outside every repo (ADR 030).

The file is ``$XDG_CONFIG_HOME/keeplane/settings.json``, which is
``~/.config/keeplane/settings.json`` by default. It is one JSON object with
three sections, each optional:

    {"runtime": "/usr/local/bin/opencode",
     "projects": {"<project ID>": {"model": "coder"}},
     "models": {"<model ID>": {"temperature": 0.2}}}

- ``runtime``: the full path to the coding runtime (task 009-03).
- ``projects``: per-project settings keyed by project ID; ``model`` is the
  developer's saved model switch for that repo (D150, task 009-07).
- ``models``: per-model request settings (Spec 004 ST26, task
  009-12), which that task checks.

Unknown keys, at any level, are ignored and kept when the file is saved, so
newer settings never break an older CLI. A known section with the wrong shape
is refused. Server and gateway addresses live in the credential profile, not
here.

A repo can never change this file, and the CLI refuses it unless only this
user can write it, because the runtime path it names is run.
"""

import fcntl
import json
import os
import secrets
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

LIMIT = 256 * 1024


class SettingsError(Exception):
    pass


def config_home():
    """``$XDG_CONFIG_HOME`` when it is an absolute path, otherwise ``~/.config``."""
    configured = os.environ.get("XDG_CONFIG_HOME", "")
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path.home() / ".config"


def path():
    return config_home() / "keeplane" / "settings.json"


def invalid(reason):
    return SettingsError("Keeplane's settings file " + str(path()) + " " + reason)


def _plain(text):
    return (
        isinstance(text, str)
        and 0 < len(text) <= 4096
        and not any(ord(c) < 32 or ord(c) == 127 for c in text)
    )


def _project_key(project_id):
    try:
        return str(uuid.UUID(str(project_id)))
    except (ValueError, TypeError, AttributeError):
        raise SettingsError("Use a valid project ID.") from None


def _model_id(model_id):
    if not _plain(model_id) or len(model_id) > 256:
        raise SettingsError("Use a valid model ID.")
    return model_id


def check(data):
    """Refuse known sections with the wrong shape; never refuse unknown keys."""
    if not isinstance(data, dict):
        raise invalid("must hold one JSON object.")
    runtime = data.get("runtime")
    if runtime is not None and (
        not _plain(runtime) or not Path(runtime).expanduser().is_absolute()
    ):
        raise invalid('has a "runtime" that isn\'t a full path to the coding runtime.')
    projects = data.get("projects")
    if projects is not None:
        if not isinstance(projects, dict):
            raise invalid('has a "projects" section that isn\'t an object.')
        for key, value in projects.items():
            try:
                valid = key == str(uuid.UUID(key)) and isinstance(value, dict)
            except (ValueError, TypeError, AttributeError):
                valid = False
            if not valid or (
                "model" in value
                and (not _plain(value["model"]) or len(value["model"]) > 256)
            ):
                raise invalid(
                    'has a "projects" entry that isn\'t a project ID with its settings.'
                )
    requests = data.get("models")
    if requests is not None and (
        not isinstance(requests, dict)
        or not all(
            _plain(key) and len(key) <= 256 and isinstance(value, dict)
            for key, value in requests.items()
        )
    ):
        raise invalid('has a "models" section that isn\'t settings per model ID.')
    return data


def _private(info):
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


def load():
    """The settings, or an empty object when there is no file yet."""
    try:
        descriptor = os.open(path(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    except OSError:
        raise invalid("can't be opened.") from None
    with os.fdopen(descriptor, "rb") as source:
        if not _private(os.fstat(source.fileno())):
            raise invalid("must be a file only you can change.")
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise invalid("is too large.")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise invalid("isn't valid JSON.") from None
    return check(data)


def _folder():
    folder = path().parent
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = os.lstat(folder)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise invalid("is in a folder that isn't yours.")
    return folder


@contextmanager
def changing():
    """Yield the current settings to change; they are saved atomically on exit."""
    try:
        folder = _folder()
        lock = os.open(
            folder / ".settings.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
    except OSError:
        raise invalid("can't be saved.") from None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load()
        yield data
        payload = (json.dumps(check(data), indent=2, sort_keys=True) + "\n").encode()
        if len(payload) > LIMIT:
            raise invalid("would be too large.")
        pending = folder / (".pending-" + secrets.token_hex(8))
        try:
            descriptor = os.open(
                pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            os.replace(pending, path())
        except OSError:
            raise invalid("can't be saved.") from None
        finally:
            pending.unlink(missing_ok=True)
    finally:
        os.close(lock)


def runtime():
    """The saved runtime path, or None."""
    value = load().get("runtime")
    return None if value is None else str(Path(value).expanduser())


def set_runtime(value):
    """Save the runtime path; None removes it."""
    with changing() as data:
        if value is None:
            data.pop("runtime", None)
        else:
            data["runtime"] = str(value)


def project_settings(project_id):
    """One project's saved settings, or an empty object."""
    return dict(load().get("projects", {}).get(_project_key(project_id), {}))


def project_model(project_id):
    """The developer's saved model switch for a project, or None."""
    return project_settings(project_id).get("model")


def set_project_model(project_id, model_id):
    """Save the model switch for a project; None clears it."""
    key = _project_key(project_id)
    if model_id is not None:
        model_id = _model_id(model_id)
    with changing() as data:
        projects = data.setdefault("projects", {})
        entry = projects.setdefault(key, {})
        if model_id is None:
            entry.pop("model", None)
            if not entry:
                del projects[key]
        else:
            entry["model"] = model_id


def request_settings(model_id):
    """A model's saved request settings, or an empty object (checked by their task)."""
    return dict(load().get("models", {}).get(_model_id(model_id), {}))


def set_request_settings(model_id, values):
    """Replace a model's request settings; None removes them."""
    model_id = _model_id(model_id)
    if values is not None and not isinstance(values, dict):
        raise SettingsError("Use an object of request settings.")
    with changing() as data:
        section = data.setdefault("models", {})
        if values is None:
            section.pop(model_id, None)
        else:
            section[model_id] = dict(values)
