"""Managed-path checks never follow resource-provided paths outside key storage."""

import os
import uuid
from pathlib import Path

import pytest
from model_registry.provider_keys import managed_key_available


@pytest.fixture
def key(tmp_path):
    root = tmp_path / "keys"
    root.mkdir(mode=0o700)
    path = root / ("key-" + uuid.uuid4().hex)
    path.write_text("synthetic-server-provider-key")
    path.chmod(0o600)
    return root, path


def test_current_contents_are_checked_without_returning_the_key(key):
    root, path = key
    assert managed_key_available(str(root), str(path)) is True
    path.unlink()
    assert managed_key_available(str(root), str(path)) is False


@pytest.mark.parametrize("value", ["  abcdefghij  ", "synthetic-unicode-provider-Ω"])
def test_storage_accepted_padding_and_utf8_remain_usable(key, value):
    root, path = key
    path.write_text(value)
    assert managed_key_available(str(root), str(path))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"short",
        b"x" * 513,
        b"x" * 2049,
        b"a" * 12 + b"\n",
        b"a" * 12 + b"\0",
        b"\xff" * 12,
        b" " * 20,
    ],
)
def test_invalid_or_oversized_key_is_unavailable(key, raw):
    root, path = key
    path.write_bytes(raw)
    assert not managed_key_available(str(root), str(path))


@pytest.mark.parametrize(
    "kind",
    [
        "outside",
        "traversal",
        "symlink",
        "directory",
        "fifo",
        "relative",
        "unmanaged-name",
        "symlink-root",
    ],
)
def test_untrusted_resource_cannot_escape_managed_storage(key, tmp_path, kind):
    root, path = key
    if kind == "outside":
        target = tmp_path / path.name
        target.write_text("synthetic-outside-key")
    elif kind == "traversal":
        target = root / ".." / path.name
    elif kind == "relative":
        root, target = Path("keys"), Path("keys") / path.name
    elif kind == "unmanaged-name":
        target = root / "other-key"
        target.write_text("synthetic-unmanaged-key")
    elif kind == "symlink-root":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        root, target = alias, alias / path.name
    else:
        path.unlink()
        target = path
        if kind == "symlink":
            outside = tmp_path / "outside-secret"
            outside.write_text("synthetic-outside-key")
            path.symlink_to(outside)
        elif kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path)
    assert not managed_key_available(str(root), str(target))


def test_unreadable_key_is_unavailable(key):
    root, path = key
    path.chmod(0)
    try:
        assert not managed_key_available(str(root), str(path))
    finally:
        path.chmod(0o600)
