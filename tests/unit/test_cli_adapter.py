import json
from pathlib import Path
import subprocess

import pytest

from components.cli.opencode_adapter import run


@pytest.mark.parametrize("native_code,event,expected", [(0, "text", 0), (0, "error", 1), (7, "text", 7)])
def test_disposable_profile_and_failure_propagation(tmp_path, monkeypatch, native_code, event, expected):
    binary = tmp_path / "opencode"
    binary.touch()
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    monkeypatch.setenv("OPENCODE_CONFIG", "/must/not/load")

    def invoke(command, **options):
        environment = options["env"]
        calls.append(environment)
        assert "OPENAI_API_KEY" not in environment
        assert "OPENCODE_CONFIG" not in environment
        assert environment["OPENCODE_CONFIG_PROJECT_DISABLE"] == "1"
        assert environment["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
        assert "synthetic-grant" not in environment["OPENCODE_CONFIG_CONTENT"]
        assert "synthetic-grant" not in json.dumps(command)
        profile = Path(environment["HOME"]).parent
        assert profile.stat().st_mode & 0o777 == 0o700
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "opencode v2.0.27\n", "")
        assert options["input"] == "Fix the file."
        assert "--standalone" in command
        assert "--auto" not in command
        return subprocess.CompletedProcess(command, native_code, json.dumps({"type": event}), "synthetic-grant")

    monkeypatch.setattr(subprocess, "run", invoke)
    result = run(binary, tmp_path, "https://gateway.test/v1", "coder", "Fix the file.", "synthetic-grant")
    assert result.returncode == expected
    assert result.stderr == "[redacted]"
    assert all(not Path(environment["HOME"]).exists() for environment in calls)


@pytest.mark.parametrize("gateway", ["http://gateway.test/v1", "https://user:key@gateway.test/v1", "https://gateway.test/v1?key=secret"])
def test_rejects_unsafe_gateway_before_launch(tmp_path, gateway):
    with pytest.raises(ValueError):
        run(tmp_path / "missing", tmp_path, gateway, "coder", "Fix.", "grant")


def test_timeout_removes_profile(tmp_path, monkeypatch):
    binary = tmp_path / "opencode"
    binary.touch()
    profiles = []

    def invoke(command, **options):
        profiles.append(Path(options["env"]["HOME"]))
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "2.0.27", "")
        raise subprocess.TimeoutExpired(command, 1, output=b"synthetic-grant")

    monkeypatch.setattr(subprocess, "run", invoke)
    with pytest.raises(subprocess.TimeoutExpired):
        run(binary, tmp_path, "http://127.0.0.1:8080/v1", "coder", "Fix.", "synthetic-grant")
    assert all(not profile.exists() for profile in profiles)


def test_rejects_wrong_runtime_version(tmp_path, monkeypatch):
    binary = tmp_path / "opencode"
    binary.touch()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1.19.0", ""))
    with pytest.raises(ValueError, match="requires OpenCode V2"):
        run(binary, tmp_path, "https://gateway.test/v1", "coder", "Fix.", "grant")
