"""Local initialization makes existing provider volumes private for resolution."""

import importlib.util
import stat
from pathlib import Path


def test_existing_provider_volume_becomes_private_without_replacing_keys(
    tmp_path, monkeypatch
):
    source = Path(__file__).resolve().parents[2] / "deploy/local/prepare_volumes.py"
    spec = importlib.util.spec_from_file_location("private_volume_prepare", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("state", "provider-keys", "secrets", "host-secrets"):
        (tmp_path / name).mkdir(mode=0o755)
    key = tmp_path / "provider-keys/key-existing"
    key.write_text("synthetic-existing-provider-key")
    key.chmod(0o600)
    for name in ("first-admin-password", "gateway-runtime-key", "gateway-admin-key"):
        (tmp_path / "host-secrets" / name).write_text("synthetic-private-credential")
    monkeypatch.setattr(module, "Path", lambda value: tmp_path / value.lstrip("/"))
    monkeypatch.setattr(module.os, "chown", lambda *args: None)
    module.prepare()
    module.prepare()
    assert stat.S_IMODE((tmp_path / "provider-keys").stat().st_mode) == 0o700
    assert key.read_text() == "synthetic-existing-provider-key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "state").stat().st_mode) == 0o755
