"""Real child processes exercise cooperative cancellation and pipe bounds."""

import json
import os
import signal
import subprocess
import sys
import time
from threading import Thread

import pytest

from components.cli.opencode_adapter import (
    Cancelled,
    Termination,
    coding_turn,
    termination_requested,
)


def test_cancelled_turn_never_spawns(tmp_path):
    cancelled = Termination()
    cancelled.request()
    with pytest.raises(Cancelled):
        coding_turn(["missing-runtime"], input="", env={}, cwd=tmp_path,
                    timeout=2, cancelled=cancelled)


@pytest.mark.parametrize("detached", [False, True])
def test_cancel_stops_owned_group_without_waiting_for_detached_pipes(tmp_path, detached):
    record, heartbeat = tmp_path / "pids", tmp_path / "heartbeat"
    child = f"import time; from pathlib import Path\nwhile True:\n Path({str(heartbeat)!r}).write_text(str(time.time_ns())); time.sleep(.02)"
    program = (
        "import json,os,subprocess,sys,time; from pathlib import Path; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session={detached}); "
        f"Path({str(record)!r}).write_text(json.dumps({{'parent':os.getpid(),'child':child.pid}})); time.sleep(30)"
    )

    def cancel_when_running():
        for _ in range(100):
            if record.exists() and heartbeat.exists():
                os.kill(os.getpid(), signal.SIGTERM)
                return
            time.sleep(.01)

    thread = Thread(target=cancel_when_running)
    thread.start()
    started = time.monotonic()
    try:
        with termination_requested() as cancelled, pytest.raises(Cancelled):
            coding_turn([sys.executable, "-c", program], input="", env={"PATH": os.defpath},
                        cwd=tmp_path, timeout=10, cancelled=cancelled)
        assert record.exists() and heartbeat.exists(), "Child control did not start"
        assert time.monotonic() - started < 2
        if not detached:
            before = heartbeat.read_bytes()
            time.sleep(.1)
            assert heartbeat.read_bytes() == before, "Cancelled tool is still running"
    finally:
        thread.join(timeout=2)
        if record.exists():
            state = json.loads(record.read_text())
            for pid, grouped in ((state["parent"], True), (state["child"], False)):
                try:
                    (os.killpg if grouped else os.kill)(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_cancellation_supervision_preserves_large_stdin(tmp_path):
    data = "buffered input " * 10000
    result = coding_turn([sys.executable, "-c", "import sys,time; time.sleep(.25); sys.stdout.write(sys.stdin.read())"],
                         input=data, env={"PATH": os.defpath}, cwd=tmp_path,
                         timeout=3, cancelled=Termination())
    assert result.returncode == 0 and result.stdout == data


def test_cancellation_supervision_retains_configured_deadline(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired) as error:
        coding_turn([sys.executable, "-c", "import time; time.sleep(30)"], input="",
                    env={"PATH": os.defpath}, cwd=tmp_path, timeout=.2, cancelled=Termination())
    assert error.value.timeout == .2


def test_termination_handler_is_restored():
    original = signal.getsignal(signal.SIGTERM)
    with termination_requested() as cancelled:
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert cancelled.requested
    assert signal.getsignal(signal.SIGTERM) == original


def test_signal_during_launch_waits_until_the_child_is_owned(tmp_path, monkeypatch):
    original, children = subprocess.Popen, []

    def launch(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return child

    monkeypatch.setattr(subprocess, "Popen", launch)
    try:
        with termination_requested() as cancelled, pytest.raises(Cancelled):
            coding_turn([sys.executable, "-c", "import time; time.sleep(30)"], input="",
                        env={"PATH": os.defpath}, cwd=tmp_path, timeout=3, cancelled=cancelled)
        assert len(children) == 1 and children[0].poll() is not None
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)


@pytest.mark.parametrize("cooperative", [True, False])
def test_native_interruption_cleans_managed_tools_or_forces_owned_group(tmp_path, cooperative):
    record = tmp_path / "pids"
    heartbeat = tmp_path / "heartbeat"
    interrupted = tmp_path / "interrupted"
    child = f"import time; from pathlib import Path\nwhile True:\n Path({str(heartbeat)!r}).write_text(str(time.time_ns())); time.sleep(.02)"
    program = f"""import json,os,signal,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session={cooperative})
def stop(*_):
 Path({str(interrupted)!r}).write_text('native interruption received')
 if {cooperative}:
  os.killpg(child.pid,signal.SIGTERM)
  child.wait(timeout=1)
  sys.exit(0)
signal.signal(signal.SIGINT,stop)
Path({str(record)!r}).write_text(json.dumps({{'parent':os.getpid(),'child':child.pid}}))
time.sleep(30)
"""

    def cancel_when_ready():
        for _ in range(200):
            if record.exists() and heartbeat.exists():
                os.kill(os.getpid(), signal.SIGTERM)
                return
            time.sleep(.01)

    thread = Thread(target=cancel_when_ready)
    thread.start()
    started = time.monotonic()
    try:
        with termination_requested() as cancelled, pytest.raises(Cancelled):
            coding_turn([sys.executable, "-c", program], input="", env={"PATH": os.defpath},
                        cwd=tmp_path, timeout=10, cancelled=cancelled)
        assert interrupted.read_text() == "native interruption received"
        assert time.monotonic() - started < (2 if cooperative else 6)
        state = json.loads(record.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(state["parent"], 0)
        if cooperative:
            with pytest.raises(ProcessLookupError):
                os.kill(state["child"], 0)
        before = heartbeat.read_bytes()
        time.sleep(.1)
        assert heartbeat.read_bytes() == before, "Owned tool is still running"
    finally:
        thread.join(timeout=2)
        if record.exists():
            state = json.loads(record.read_text())
            for pid, grouped in ((state["parent"], True), (state["child"], cooperative)):
                try:
                    (os.killpg if grouped else os.kill)(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
