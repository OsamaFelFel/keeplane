"""Private initialization disables enrollment before validating credentials."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / "deploy/local/prepare_runtime.py"
spec = importlib.util.spec_from_file_location("runtime_preparation", FILE)
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


@pytest.fixture
def files(tmp_path, monkeypatch):
    installation = tmp_path / "installed"
    installation.mkdir()
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    template = Path(__file__).resolve().parents[2] / "deploy/local/runtime-base.json"
    for name in ("admin", "runtime"):
        (secrets / ("gateway-" + name + "-key")).write_text(
            "synthetic-" + name + "-" + "a" * 32
        )

    def path(value):
        value = str(value)
        return (
            secrets
            if value == "/run/secrets"
            else template
            if value == "/runtime-base.json"
            else Path(value)
        )

    monkeypatch.setattr(preparation, "ROOT", installation)
    monkeypatch.setattr(preparation, "Path", path)
    # Host unit tests cannot chown to the container account. Native acceptance
    # checks that boundary; these cases isolate ordering and private file modes.
    monkeypatch.setattr(preparation.os, "chown", lambda *args: None)
    monkeypatch.setattr(preparation.os, "fchown", lambda *args: None)
    return installation, secrets


def test_current_operator_hashes_and_callback_survive_fresh_preparation(files):
    installation, secrets = files
    preparation.prepare()
    callback = (installation / "callback-key").read_bytes()
    trusted = (installation / "trusted.json").read_bytes()
    assert trusted == (installation / "gateway.json").read_bytes()
    value = json.loads(trusted)
    for name, section in (("admin", "ui"), ("runtime", "llm")):
        raw = (secrets / ("gateway-" + name + "-key")).read_bytes()
        assert (
            value[section]["policies"]["apiKey"]["keys"][0]["keyHash"]
            == "sha256:" + hashlib.sha256(raw).hexdigest()
        )
    (installation / "manifest.json").write_text('{"enabled":true}')
    preparation.prepare()
    assert (installation / "callback-key").read_bytes() == callback
    assert json.loads((installation / "manifest.json").read_text()) == {
        "version": 2,
        "enabled": False,
    }
    assert installation.stat().st_mode & 0o077 == 0
    assert all(
        (installation / name).stat().st_mode & 0o077 == 0
        for name in ("manifest.json", "callback-key", "trusted.json", "gateway.json")
    )


@pytest.mark.parametrize(
    "fault", ["invalid-operator", "symlink-operator", "invalid-callback"]
)
def test_invalid_credentials_leave_disabled_manifest_and_existing_config(files, fault):
    installation, secrets = files
    preparation.prepare()
    before = (installation / "gateway.json").read_bytes()
    (installation / "manifest.json").write_text('{"enabled":true}')
    if fault == "invalid-callback":
        (installation / "callback-key").write_text("invalid")
    else:
        key = secrets / "gateway-admin-key"
        key.unlink()
        if fault == "invalid-operator":
            key.write_text("invalid")
        else:
            key.symlink_to(secrets / "gateway-runtime-key")
    with pytest.raises((ValueError, OSError)):
        preparation.prepare()
    assert json.loads((installation / "manifest.json").read_text())["enabled"] is False
    assert (installation / "gateway.json").read_bytes() == before
