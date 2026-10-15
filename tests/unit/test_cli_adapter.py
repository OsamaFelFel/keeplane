import json
from pathlib import Path
import subprocess

import pytest

from components.cli.opencode_adapter import run
from components.cli import opencode_adapter


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
    monkeypatch.setattr(opencode_adapter, "coding_turn", invoke)
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
    monkeypatch.setattr(opencode_adapter, "coding_turn", invoke)
    with pytest.raises(subprocess.TimeoutExpired):
        run(binary, tmp_path, "http://127.0.0.1:8080/v1", "coder", "Fix.", "synthetic-grant")
    assert all(not profile.exists() for profile in profiles)


def test_rejects_wrong_runtime_version(tmp_path, monkeypatch):
    binary = tmp_path / "opencode"
    binary.touch()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1.19.0", ""))
    with pytest.raises(ValueError, match="requires OpenCode V2"):
        run(binary, tmp_path, "https://gateway.test/v1", "coder", "Fix.", "grant")


def test_timeout_terminates_spawned_tool(tmp_path):
    import os
    import sys
    import time

    pid_file = tmp_path / "child.pid"
    child = "import time; time.sleep(30)"
    program = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        opencode_adapter.coding_turn([sys.executable, "-c", program], input="",
                                     env=dict(os.environ), cwd=tmp_path, timeout=1)
    pid = pid_file.read_text()
    for _ in range(20):
        state = subprocess.run(["ps", "-o", "stat=", "-p", pid], capture_output=True, text=True).stdout.strip()
        if not state or state.startswith("Z"):
            break
        time.sleep(0.05)
    assert not state or state.startswith("Z"), "Timed-out tool is still running."


def test_detached_child_holding_pipes_does_not_extend_timeout(tmp_path):
    import os
    import signal
    import sys
    import time

    pid_file = tmp_path / "detached.pid"
    program = (
        "import subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True); "
        f"Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(30)"
    )
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            opencode_adapter.coding_turn([sys.executable, "-c", program], input="",
                                         env=dict(os.environ), cwd=tmp_path, timeout=1)
        assert time.monotonic() - started < 3
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("grant", ['quote"token', "back\\slash", "nonascii-é", "slash/token"])
def test_escaped_token_alphabets_are_rejected_before_launch(tmp_path, grant):
    with pytest.raises(ValueError, match="credentials must use only"):
        run(tmp_path / "missing", tmp_path, "https://gateway.test/v1", "coder", "Fix.", grant)


def test_actual_json_event_credential_redaction(tmp_path, monkeypatch):
    binary, grant = tmp_path / "opencode", "synthetic-grant_A.1~2"
    binary.touch()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "2.0.27", ""))
    event = json.dumps({"type": "error", "error": {"message": "Refused Bearer " + grant}})
    monkeypatch.setattr(opencode_adapter, "coding_turn", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, event, event))
    result = run(binary, tmp_path, "https://gateway.test/v1", "coder", "Fix.", grant)
    assert result.returncode == 1
    assert grant not in result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["message"] == "Refused Bearer [redacted]"
