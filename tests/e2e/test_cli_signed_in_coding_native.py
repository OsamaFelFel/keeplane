"""Actual pinned runtime through the profile command; synthetic account server."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

if __name__ != "__main__":
    import pytest
    pytestmark = pytest.mark.optional

from components.cli.credential_profile import Credential, opened
from tests.fixtures.cli_coding_provider import Handler, start

ROOT = Path(__file__).resolve().parents[2]


def native_signed_in(binary):
    assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    actor, project = str(uuid.uuid4()), str(uuid.uuid4())
    access, refresh = "kpc_" + "a" * 43, "kpr_" + "r" * 43
    current = {"actor": actor, "access": access}

    class Account(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def answer(self, value, status=200):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.headers.get("Authorization") != "Bearer " + current["access"]:
                return self.answer({}, 401)
            if self.path == "/api/runtime/session":
                return self.answer({"id": current["actor"], "username": "developer", "role": "developer"})
            return self.answer({"project_id": self.path.split("/")[-2], "models": [{"id": "fixture-coder"}]})

        def do_POST(self):
            self.answer(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))

    class Provider(Handler):
        phase, sessions, contacts, continued = 1, set(), 0, 0

        def do_POST(self):
            type(self).contacts += 1
            assert self.headers.get("X-Keeplane-Project-ID") == project
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            self.rfile = io.BytesIO(raw)
            body = json.loads(raw)
            if body.get("tools"):
                self.sessions.add(self.headers["x-opencode-session-id"])
                if self.phase == 2:
                    last = max(i for i, row in enumerate(body["messages"]) if row.get("role") == "user")
                    history = body["messages"][:last]
                    assert "FIRST_ACCOUNT_TURN" in json.dumps(history)
                    calls = {call["id"]: call["function"]["name"] for row in history for call in row.get("tool_calls", [])}
                    results = {row["tool_call_id"] for row in history if row.get("role") == "tool" and row.get("content")}
                    assert set(calls.values()) == {"read", "edit"} and set(calls) <= results
                    type(self).continued += 1
            super().do_POST()

    with tempfile.TemporaryDirectory(prefix="keeplane-signed-in-native-") as temporary:
        root = Path(temporary)
        directory = root / "repository"
        directory.mkdir()
        target = directory / "math.py"
        target.write_text("def add(a, b):\n    return a - b\n")
        profile, state = root / "account", root / "history"
        account = ThreadingHTTPServer(("127.0.0.1", 0), Account)
        provider = start(target, handler=Provider, turn_scoped=True)
        threads = [Thread(target=server.serve_forever, daemon=True) for server in (account, provider)]
        issuer = f"http://127.0.0.1:{account.server_port}"

        def save():
            with opened(profile, create=True) as stored:
                stored.save(Credential(issuer, current["actor"], current["access"], refresh))

        command = [sys.executable, str(ROOT / "components/cli/keeplane.py"), "code",
                   "--profile", str(profile), "--project", project, "--name", "Native CLI trial",
                   "--model", "fixture-coder", "--runtime", binary,
                   "--gateway", f"http://127.0.0.1:{provider.server_port}/v1",
                   "--directory", str(directory), "--state-dir", str(state), "--timeout", "40"]

        def invoke(prompt, session=None):
            result = subprocess.run(command + (["--session", session] if session else []) + [prompt],
                                    check=False, capture_output=True, text=True, timeout=50)
            assert current["access"] not in result.stdout + result.stderr
            assert refresh not in result.stdout + result.stderr
            return result

        original = Handler.grant
        try:
            for thread in threads:
                thread.start()
            Handler.grant = access
            save()
            first = invoke("FIRST_ACCOUNT_TURN: fix the addition function in math.py.")
            assert first.returncode == 0 and Handler.calls == ["read", "edit"], (first.stdout, first.stderr)
            assert target.read_text() == "def add(a, b):\n    return a + b\n"
            assert len(Provider.sessions) == 1
            session = next(iter(Provider.sessions))
            target.write_text("def add(a, b):\n    return a - b\n")
            current["access"] = Handler.grant = "kpc_" + "b" * 43
            save()
            Handler.calls, Handler.call_prefix, Provider.phase = [], "second_", 2
            second = invoke("SECOND_ACCOUNT_TURN: fix addition again.", session)
            assert second.returncode == 0 and Handler.calls == ["read", "edit"], (second.stdout, second.stderr)
            assert target.read_text() == "def add(a, b):\n    return a + b\n"
            assert Provider.sessions == {session} and Provider.continued >= 3
            contacts = Provider.contacts
            current["actor"] = str(uuid.uuid4())
            save()
            assert invoke("Do not reuse another account's history.", session).returncode != 0
            assert Provider.contacts == contacts
            current["actor"] = actor
            save()
            current["access"] = "withdrawn"
            assert invoke("Do not start another withdrawn turn.", session).returncode != 0
            assert Provider.contacts == contacts
            for path in state.iterdir():
                assert path.stat().st_mode & 0o777 == 0o600
                assert all(value.encode() not in path.read_bytes() for value in (access, Handler.grant, refresh))
        finally:
            Handler.grant = original
            for server in (account, provider):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=3)


def test_native_signed_in_coding_and_account_bound_resume():
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime.")
    native_signed_in(binary)


if __name__ == "__main__":
    native_signed_in(os.environ["KEEPLANE_OPENCODE_V2_BIN"])
