"""Optional pinned native cancellation against a stalled synthetic provider."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from threading import Event, Thread

if __name__ != "__main__":
    import pytest
    pytestmark = pytest.mark.optional


def native_cancellation(binary, hard_kill=False):
    assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    started, release = Event(), Event()
    grant = "synthetic-cancellation-grant"

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Authorization") != "Bearer " + grant:
                self.send_error(401)
                return
            started.set()
            release.wait(10)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory(prefix="keeplane-native-cancel-") as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        record, wrapper = project / "runtime.json", project / "runtime"
        # exec preserves the native PID; this wrapper only records cleanup paths.
        wrapper.write_text(f'#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nif "--version" not in sys.argv:\n Path({str(record)!r}).write_text(json.dumps({{"pid":os.getpid(),"profile":str(Path(os.environ["HOME"]).parent)}}))\nos.execv({str(binary)!r},[{str(binary)!r},*sys.argv[1:]])\n')
        wrapper.chmod(0o700)
        adapter = Path(__file__).resolve().parents[2] / "components/cli/opencode_adapter.py"
        process = subprocess.Popen([sys.executable, str(adapter), "--runtime", str(wrapper),
                                    "--gateway", f"http://127.0.0.1:{server.server_port}/v1",
                                    "--model", "fixture-coder", "--directory", str(project),
                                    *(["--state-dir", str(root / "sessions")] if hard_kill else []), "Fix the file."],
                                   env=dict(os.environ, KEEPLANE_GATEWAY_GRANT=grant),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            if not started.wait(15):
                process.terminate()
                output, errors = process.communicate(timeout=12)
                raise AssertionError("Native provider control did not start: " + (output + errors).replace(grant, "[redacted]"))
            state = json.loads(record.read_text())
            if hard_kill:
                from components.cli.session_state import discard
                process.kill()
                process.wait(timeout=3)
                os.kill(state["pid"], 0)  # The actual native parent remains active.
                try:
                    discard(root / "sessions")
                except ValueError as error:
                    assert str(error) == "Session state is already in use."
                else:
                    raise AssertionError("Native runtime dropped the inherited state lock")
                os.killpg(state["pid"], 9)
                release.set()
                deadline = time.monotonic() + 3
                while True:
                    try:
                        discard(root / "sessions")
                        break
                    except ValueError:
                        assert time.monotonic() < deadline, "Native state lock did not release"
                        time.sleep(0.03)
                return
            process.terminate()
            output, errors = process.communicate(timeout=3)
            assert process.returncode == 143, (output, errors)
            assert grant not in output + errors
            assert not Path(state["profile"]).exists()
            try:
                os.kill(state["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("Native runtime survived cancellation")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            if record.exists():
                state = json.loads(record.read_text())
                try:
                    os.killpg(state["pid"], 9)
                except ProcessLookupError:
                    pass
                if hard_kill:
                    shutil.rmtree(state["profile"], ignore_errors=True)
            for stream in (process.stdout, process.stderr):
                stream.close()
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


def test_native_sigterm_cancellation():
    import pytest
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime")
    native_cancellation(binary)


def test_native_state_lock_survives_wrapper_hard_kill():
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime")
    native_cancellation(binary, hard_kill=True)


if __name__ == "__main__":
    native_cancellation(os.environ["KEEPLANE_OPENCODE_V2_BIN"], hard_kill=sys.argv[1:] == ["lock"])
