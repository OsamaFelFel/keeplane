"""Optional actual CLI continuation with private history and fresh test grants."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Thread

if __name__ != "__main__":
    import pytest

    pytestmark = pytest.mark.optional

from tests.fixtures.cli_coding_provider import Handler, start

ROOT = Path(__file__).resolve().parents[2]


class Provider(Handler):
    phase = 1
    sessions = set()
    continued = 0
    contacts = 0

    def do_POST(self):
        type(self).contacts += 1
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        self.rfile = io.BytesIO(raw)
        body = json.loads(raw)
        if body.get("tools") and self.headers.get("Authorization") == "Bearer " + self.grant:
            self.sessions.add(self.headers["x-opencode-session-id"])
            if self.phase == 2:
                last = max(index for index, row in enumerate(body["messages"]) if row.get("role") == "user")
                history = body["messages"][:last]
                assert "FIRST_SAVED_TURN" in json.dumps(history)
                calls = {call["id"]: call["function"] for row in history for call in row.get("tool_calls", [])}
                results = {row["tool_call_id"] for row in history if row.get("role") == "tool" and row.get("content")}
                assert {row["name"] for row in calls.values()} == {"read", "edit"}
                assert set(calls) <= results
                for call in calls.values():
                    arguments = json.loads(call["arguments"])
                    assert arguments["path"] == str(self.target)
                    if call["name"] == "edit":
                        assert arguments["oldString"] == "return a - b" and arguments["newString"] == "return a + b"
                type(self).continued += 1
        super().do_POST()


def native_resume(binary):
    assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    Provider.phase, Provider.sessions, Provider.continued, Provider.contacts = 1, set(), 0, 0
    original_grant = Handler.grant
    Handler.grant = "synthetic-initial-resume-grant"
    with tempfile.TemporaryDirectory(prefix="keeplane-cli-resume-") as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        target, state = project / "math.py", root / "sessions"
        target.write_text("def add(a, b):\n    return a - b\n")
        server = start(target, handler=Provider, turn_scoped=True)
        Handler.call_prefix = "first_"
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        command = [sys.executable, str(ROOT / "components/cli/opencode_adapter.py"), "--runtime", binary,
                   "--gateway", f"http://127.0.0.1:{server.server_port}/v1", "--model", "fixture-coder",
                   "--directory", str(project), "--state-dir", str(state), "--timeout", "40"]

        def invoke(prompt, grant, session=None):
            args = command + (["--session", session] if session else []) + [prompt]
            result = subprocess.run(args, env=dict(os.environ, KEEPLANE_GATEWAY_GRANT=grant), capture_output=True, text=True, timeout=50)
            assert grant not in result.stdout + result.stderr
            return result

        try:
            first = invoke("FIRST_SAVED_TURN: fix addition in math.py.", Handler.grant)
            assert first.returncode == 0 and Handler.calls == ["read", "edit"], (first.stdout, first.stderr)
            assert len(Provider.sessions) == 1
            session = next(iter(Provider.sessions))
            assert any(json.loads(line).get("sessionID") == session for line in first.stdout.splitlines() if line.startswith("{"))
            target.write_text("def add(a, b):\n    return a - b\n")
            Handler.calls, Provider.phase = [], 2
            Handler.call_prefix = "second_"
            first_grant = Handler.grant
            Handler.grant = "synthetic-fresh-resume-grant"
            second = invoke("SECOND_RESUMED_TURN: fix addition again.", Handler.grant, session)
            assert second.returncode == 0 and Handler.calls == ["read", "edit"], (second.stdout, second.stderr)
            assert target.read_text() == "def add(a, b):\n    return a + b\n"
            assert Provider.sessions == {session} and Provider.continued >= 3
            contacts = Provider.contacts
            missing = invoke("Do not create a replacement for an unknown session.", Handler.grant, "ses_missing")
            assert missing.returncode != 0 and Provider.contacts == contacts
            denied = invoke("Do not edit without a valid grant.", "invalid-resume-grant", session)
            assert denied.returncode != 0 and Handler.calls == ["read", "edit"]
            for path in state.iterdir():
                assert path.stat().st_mode & 0o777 == 0o600
                assert all(grant.encode() not in path.read_bytes() for grant in (first_grant, Handler.grant, "invalid-resume-grant"))
            removed = subprocess.run([sys.executable, str(ROOT / "components/cli/session_state.py"), "--discard", str(state)], capture_output=True, text=True, timeout=5)
            assert removed.returncode == 0 and (state / "runtime.db").stat().st_size == 0
            assert invoke("Cannot resume removed history.", Handler.grant, session).returncode != 0
            assert Handler.calls == ["read", "edit"]
        finally:
            Handler.grant = original_grant
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


def test_native_private_session_resume():
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime.")
    native_resume(binary)


if __name__ == "__main__":
    native_resume(os.environ["KEEPLANE_OPENCODE_V2_BIN"])
