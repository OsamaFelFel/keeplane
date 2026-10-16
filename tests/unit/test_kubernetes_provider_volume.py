"""Existing keys survive permission repair and a repeat after volume remount."""

import os
import stat
from types import SimpleNamespace

import pytest
from prepare_provider_volume import prepare

NAME = "key-" + "1" * 32


def repair(root):
    prepare(root, uid=os.geteuid(), gid=os.getegid())


def test_existing_files_and_paths_survive_repair_and_remount(tmp_path):
    root = tmp_path / "keys"
    root.mkdir(mode=0o777)
    key = root / NAME
    key.write_bytes(b"synthetic-provider-key")
    key.chmod(0o660)
    original = key.stat().st_ino
    unrelated = root / "operator-notes"
    unrelated.write_bytes(b"preserve this file")
    unrelated.chmod(0o640)
    for _ in range(2):
        repair(root)
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(key.stat().st_mode) == 0o600
        assert key.stat().st_ino == original
        assert key.read_bytes() == b"synthetic-provider-key"
        assert unrelated.read_bytes() == b"preserve this file"
        assert stat.S_IMODE(unrelated.stat().st_mode) == 0o640
        # Model the group bits that volume ownership setup can add.
        root.chmod(0o2770)
        key.chmod(0o660)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo"])
def test_unsafe_managed_entry_is_refused_without_touching_its_target(tmp_path, kind):
    root = tmp_path / "keys"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"do not modify")
    outside.chmod(0o640)
    key = root / NAME
    if kind == "symlink":
        key.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, key)
    elif kind == "directory":
        key.mkdir()
    else:
        os.mkfifo(key)
    with pytest.raises(ValueError):
        repair(root)
    assert outside.read_bytes() == b"do not modify"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o640


def test_symlinked_volume_is_refused(tmp_path):
    link = tmp_path / "linked-root"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        repair(link)


def test_disappearing_old_key_does_not_block_startup(tmp_path, monkeypatch):
    key = tmp_path / NAME
    key.write_bytes(b"synthetic-provider-key")
    original = os.stat

    def removed(name, **options):
        if name == NAME and "dir_fd" in options:
            key.unlink()
        return original(name, **options)

    monkeypatch.setattr(os, "stat", removed)
    repair(tmp_path)
    assert not key.exists()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_foreign_owner_metadata_fault_is_refused(tmp_path, monkeypatch):
    key = tmp_path / NAME
    key.write_bytes(b"synthetic-provider-key")
    key.chmod(0o640)
    original = os.stat

    def foreign_owner(name, **options):
        info = original(name, **options)
        if name == NAME and "dir_fd" in options:
            return SimpleNamespace(st_mode=info.st_mode, st_nlink=1, st_uid=55555)
        return info

    monkeypatch.setattr(os, "stat", foreign_owner)
    with pytest.raises(ValueError):
        repair(tmp_path)
    assert key.read_bytes() == b"synthetic-provider-key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o640


def test_replaced_inode_is_refused_before_ownership_change(tmp_path, monkeypatch):
    key = tmp_path / NAME
    key.write_bytes(b"original-synthetic-key")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement-synthetic-key")
    replacement.chmod(0o640)
    original = os.open

    def changed(name, flags, **options):
        if name == NAME:
            replacement.replace(key)
        return original(name, flags, **options)

    monkeypatch.setattr(os, "open", changed)
    with pytest.raises(ValueError):
        repair(tmp_path)
    assert key.read_bytes() == b"replacement-synthetic-key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o640
