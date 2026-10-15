import json
import os
import stat
import uuid

import pytest

from components.cli.credential_profile import Credential, ProfileError, opened


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "profile"
    credential = Credential(
        "https://keeplane.example",
        str(uuid.uuid4()),
        "kpc_" + "a" * 43,
        "refresh_" + "b" * 32,
    )
    with opened(path, create=True) as profile:
        profile.save(credential)
    return path, credential


def test_private_atomic_roundtrip_lock_and_redacted_representation(saved):
    path, credential = saved
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in path.iterdir())
    assert credential.access_token not in repr(credential)
    assert credential.refresh_token not in str(credential)
    with opened(path) as profile:
        assert profile.load() == credential
        with pytest.raises(ProfileError, match="already in use"), opened(path):
            pytest.fail("Concurrent access must be refused")
        profile.save(
            Credential(
                credential.issuer,
                credential.actor_id,
                "kpc_" + "c" * 43,
                credential.refresh_token,
            )
        )
    with opened(path) as profile:
        assert profile.load().access_token == "kpc_" + "c" * 43
    assert {item.name for item in path.iterdir()} == {"lock", "credential.json"}


@pytest.mark.parametrize(
    "unsafe",
    [
        "directory_mode",
        "file_mode",
        "symlink",
        "hardlink",
        "fifo",
        "foreign",
        "oversize",
        "malformed",
    ],
)
def test_unsafe_or_foreign_state_fails_without_secret_output(saved, tmp_path, unsafe):
    path, credential = saved
    target = path / "credential.json"
    if unsafe == "directory_mode":
        path.chmod(0o755)
    elif unsafe == "file_mode":
        target.chmod(0o644)
    elif unsafe in {"symlink", "hardlink", "fifo"}:
        target.rename(tmp_path / "outside")
        if unsafe == "symlink":
            target.symlink_to(tmp_path / "outside")
        elif unsafe == "hardlink":
            os.link(tmp_path / "outside", target)
        else:
            os.mkfifo(target, 0o600)
    elif unsafe == "foreign":
        (path / "auth.json").write_text("foreign credential")
    else:
        target.write_bytes(b"x" * 4097 if unsafe == "oversize" else b"[invalid")
    with pytest.raises(ProfileError) as error, opened(path) as profile:
        profile.load()
    assert credential.access_token not in str(error.value)
    assert str(path) not in str(error.value)


def test_root_symlink_owner_and_missing_read_are_refused(saved, tmp_path, monkeypatch):
    path, _ = saved
    alias = tmp_path / "alias"
    alias.symlink_to(path, target_is_directory=True)
    for candidate in [alias, tmp_path / "missing"]:
        with pytest.raises(ProfileError), opened(candidate):
            pytest.fail("Unsafe profile opened")
    assert not (tmp_path / "missing").exists()
    monkeypatch.setattr(os, "geteuid", lambda: -1)
    with pytest.raises(ProfileError), opened(path):
        pytest.fail("Other owner's profile opened")


def test_failed_replace_preserves_old_credential_and_cleans_pending(saved, monkeypatch):
    path, credential = saved

    def fail(*args, **kwargs):
        raise OSError("do not export path or credential")

    with pytest.raises(ProfileError), opened(path) as profile:
        monkeypatch.setattr(os, "replace", fail)
        profile.save(credential)
    assert {item.name for item in path.iterdir()} == {"lock", "credential.json"}
    assert (
        json.loads((path / "credential.json").read_text())["access_token"]
        == credential.access_token
    )
