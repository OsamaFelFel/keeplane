import json
import os
import socket
import stat
import uuid

import pytest

from components.cli.credential_profile import (
    UNUSABLE_SERVER,
    Credential,
    ProfileError,
    UnusableServer,
    opened,
    saved_server,
)


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


# Spec 009 ST29 "Sign out": only the non-secret server address is kept.
def test_forget_keeps_only_the_server_address_privately(saved):
    path, credential = saved
    with opened(path) as profile:
        assert profile.load_server() is None
        profile.forget()
    assert {item.name for item in path.iterdir()} == {"lock", "server.json"}
    assert stat.S_IMODE((path / "server.json").stat().st_mode) == 0o600
    raw = (path / "server.json").read_text()
    assert json.loads(raw) == {
        "format": "keeplane-server-v1",
        "server": "https://keeplane.example",
    }
    for secret in (
        credential.access_token,
        credential.refresh_token,
        credential.actor_id,
    ):
        assert secret not in raw
    assert saved_server(path) == "https://keeplane.example"
    with opened(path) as profile, pytest.raises(FileNotFoundError):
        profile.load()


def test_saved_server_is_none_without_a_profile_or_a_kept_address(tmp_path, saved):
    assert saved_server(tmp_path / "missing") is None
    assert saved_server(saved[0]) is None


@pytest.mark.parametrize(
    "content",
    [
        b'{"format": "keeplane-server-v1", "server": "https://a.example/path"}',
        b'{"format": "keeplane-server-v1", "server": "https://a.example", "x": 1}',
        b'{"format": "keeplane-server-v2", "server": "https://a.example"}',
        b'{"format": "keeplane-server-v1", "server": 7}',
        (
            b'{"format": "keeplane-server-v1", "server": "https://a.example",'
            b' "server": "https://b.example"}'
        ),
        b"[]",
        b"x" * 4097,
    ],
)
def test_an_unusable_server_address_is_refused(saved, content):
    path, _ = saved
    with opened(path) as profile:
        profile.forget()
    (path / "server.json").write_bytes(content)
    with pytest.raises(UnusableServer) as error:
        saved_server(path)
    assert str(error.value) == UNUSABLE_SERVER


VALID_SERVER = b'{"format": "keeplane-server-v1", "server": "https://a.example"}'


def make_unsafe(path, outside, unsafe):
    """Leave an unsafe server.json whose content would otherwise be valid."""
    target = path / "server.json"
    outside.write_bytes(VALID_SERVER)
    outside.chmod(0o600)
    if unsafe == "file_mode":
        target.write_bytes(VALID_SERVER)
        target.chmod(0o644)
    elif unsafe == "symlink":
        target.symlink_to(outside)
    elif unsafe == "dangling symlink":
        target.symlink_to(outside.parent / "nowhere")
    elif unsafe == "hardlink":
        os.link(outside, target)
    elif unsafe == "socket":
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(target))
        listener.close()
        target.chmod(0o600)
    elif unsafe == "foreign owner":
        target.write_bytes(VALID_SERVER)
        target.chmod(0o600)
        owner = target.lstat().st_uid
        real = os.stat

        def foreign(name, *args, **kwargs):
            info = real(name, *args, **kwargs)
            if name == "server.json" or str(name).endswith("/server.json"):
                fields = list(info)
                fields[stat.ST_UID] = owner + 1
                return os.stat_result(fields)
            return info

        return foreign
    else:
        os.mkfifo(target, 0o600)


UNSAFE_SERVER = [
    "file_mode",
    "symlink",
    "dangling symlink",
    "hardlink",
    "fifo",
    "socket",
    "foreign owner",
]


@pytest.mark.parametrize("unsafe", UNSAFE_SERVER)
def test_an_unsafe_server_file_is_refused_without_being_read(
    saved, tmp_path, monkeypatch, unsafe
):
    path, _ = saved
    with opened(path) as profile:
        profile.forget()
    (path / "server.json").unlink()
    foreign = make_unsafe(path, tmp_path / "outside", unsafe)
    if foreign:
        monkeypatch.setattr(os, "stat", foreign)

        def never(*args, **kwargs):
            raise AssertionError("another user's server.json must not be opened")

        real_open = os.open
        monkeypatch.setattr(
            os,
            "open",
            lambda name, *a, **k: (
                never() if name == "server.json" else real_open(name, *a, **k)
            ),
        )
    with pytest.raises(UnusableServer) as error:
        saved_server(path)
    assert str(error.value) == UNUSABLE_SERVER
    assert str(path) not in str(error.value)


@pytest.mark.parametrize("unsafe", UNSAFE_SERVER)
def test_an_unusable_server_file_does_not_block_the_profile(
    saved, tmp_path, monkeypatch, unsafe
):
    # `login --server` must work: the profile opens and saves without the file.
    path, credential = saved
    foreign = make_unsafe(path, tmp_path / "outside", unsafe)
    if foreign:
        monkeypatch.setattr(os, "stat", foreign)
    with opened(path) as profile:
        assert profile.load() == credential
        with pytest.raises(UnusableServer):
            profile.load_server()
    assert (tmp_path / "outside").read_bytes() == VALID_SERVER


@pytest.mark.parametrize("unsafe", [*UNSAFE_SERVER, "malformed"])
def test_remove_unusable_server_unlinks_only_the_bad_entry(
    saved, tmp_path, monkeypatch, unsafe
):
    path, _ = saved
    with opened(path) as profile:
        profile.forget()
    (path / "server.json").unlink()
    if unsafe == "malformed":
        (path / "server.json").write_bytes(b"[invalid")
        (path / "server.json").chmod(0o600)
    else:
        foreign = make_unsafe(path, tmp_path / "outside", unsafe)
        if foreign:
            monkeypatch.setattr(os, "stat", foreign)
    with opened(path) as profile:
        assert profile.remove_unusable_server() is True
    assert {item.name for item in path.iterdir()} == {"lock"}
    if unsafe != "malformed":
        # A link's target is never touched.
        assert (tmp_path / "outside").read_bytes() == VALID_SERVER
    assert saved_server(path) is None


def test_remove_unusable_server_keeps_a_usable_address(saved):
    path, _ = saved
    with opened(path) as profile:
        profile.forget()
        assert profile.remove_unusable_server() is False
    assert saved_server(path) == "https://keeplane.example"


def test_sign_out_replaces_an_unusable_server_file(saved, tmp_path):
    path, _ = saved
    make_unsafe(path, tmp_path / "outside", "symlink")
    with opened(path) as profile:
        profile.forget()
    assert not (path / "server.json").is_symlink()
    assert saved_server(path) == "https://keeplane.example"
    assert (tmp_path / "outside").read_bytes() == VALID_SERVER


def test_a_server_json_directory_still_blocks_the_profile(saved):
    path, _ = saved
    (path / "server.json").mkdir(mode=0o700)
    with pytest.raises(ProfileError, match="unsafe file"), opened(path):
        pytest.fail("A directory in the profile must be refused")
