import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from components.cli.session_state import discard, managed


@pytest.fixture
def state(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    binding = {
        "directory": str(project),
        "gateway": "https://gateway.test/v1",
        "model": "coder",
        "version": "2.0.27",
    }
    root = tmp_path / "session"
    with managed(root, binding, None):
        pass
    return root, binding


def database(root, credential=False):
    with sqlite3.connect(root / "runtime.db") as connection:
        connection.execute("CREATE TABLE credential(value TEXT)")
        connection.execute("CREATE TABLE history(message TEXT)")
        connection.execute("INSERT INTO history VALUES ('Synthetic prior turn')")
        if credential:
            connection.execute("INSERT INTO credential VALUES ('must-not-import')")


def test_private_reuse_and_explicit_history_reset(state):
    root, binding = state
    database(root)
    with (
        managed(root, binding, "ses_first") as handle,
        sqlite3.connect(handle.database) as connection,
    ):
        assert (
            connection.execute("SELECT message FROM history").fetchone()[0]
            == "Synthetic prior turn"
        )
    assert root.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
    lock_inode = (root / "lock").stat().st_ino
    discard(root)
    assert (root / "runtime.db").stat().st_size == 0
    assert (root / "lock").stat().st_ino == lock_inode
    with pytest.raises(ValueError, match="empty"), managed(root, binding, "ses_first"):
        pass
    with managed(root, binding, None):
        pass


@pytest.mark.parametrize("field", ["directory", "gateway", "model", "version"])
def test_refuses_changed_binding(state, field):
    root, binding = state
    with (
        pytest.raises(ValueError, match="changed"),
        managed(root, dict(binding, **{field: "changed"}), None),
    ):
        pass


@pytest.mark.parametrize(
    "unsafe",
    [
        "public-root",
        "public-file",
        "symlink",
        "hardlink",
        "fifo-lock",
        "foreign-config",
    ],
)
def test_refuses_unsafe_or_foreign_state(state, unsafe):
    root, binding = state
    if unsafe == "public-root":
        root.chmod(0o755)
    elif unsafe == "public-file":
        (root / "runtime.db").chmod(0o644)
    elif unsafe == "symlink":
        (root / "runtime.db").unlink()
        (root / "runtime.db").symlink_to(root.parent / "foreign")
    elif unsafe == "hardlink":
        os.link(root / "runtime.db", root.parent / "foreign")
    elif unsafe == "fifo-lock":
        (root / "lock").unlink()
        os.mkfifo(root / "lock", 0o600)
    else:
        (root / "auth.json").write_text("must-not-import")
    with pytest.raises((ValueError, OSError)), managed(root, binding, None):
        pass


def test_foreign_database_without_marker_is_not_opened(state, monkeypatch):
    root, binding = state
    (root / "binding.json").unlink()
    monkeypatch.setattr(
        sqlite3, "connect", lambda *args, **kwargs: pytest.fail("Foreign DB opened")
    )
    with (
        pytest.raises(ValueError, match="existing or incomplete"),
        managed(root, binding, None),
    ):
        pass


def test_stored_credentials_are_not_read_or_used(state):
    root, binding = state
    database(root, credential=True)
    with (
        pytest.raises(ValueError, match="contains credentials") as error,
        managed(root, binding, None),
    ):
        pass
    assert "must-not-import" not in str(error.value)


def test_inherited_lock_survives_caller_close_until_runtime_child_stops(state):
    root, binding = state
    process = None
    try:
        with managed(root, binding, None) as handle:
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                pass_fds=(handle.lock,),
            )
        with (
            pytest.raises(ValueError, match="already in use"),
            managed(root, binding, None),
        ):
            pass
    finally:
        if process:
            process.terminate()
            process.wait(timeout=2)
    with managed(root, binding, None):
        pass


def test_state_cannot_be_kept_in_repository_and_resume_requires_existing_state(state):
    root, binding = state
    for path, session in (
        (Path(binding["directory"]) / "history", None),
        (root.parent / "missing", "ses_missing"),
    ):
        with pytest.raises(ValueError), managed(path, binding, session):
            pass
        assert not path.exists()
    missing = root.parent / "missing-discard"
    with pytest.raises(ValueError):
        discard(missing)
    assert not missing.exists()
