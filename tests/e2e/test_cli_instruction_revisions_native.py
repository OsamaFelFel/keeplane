"""Optional current-rule versus resumed-context control for pinned V2."""

import base64
from collections import Counter
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
from threading import Thread
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

if __name__ != "__main__":
    import pytest

    pytestmark = pytest.mark.optional

RULES = ["SYNTHETIC_RULE_A", "SYNTHETIC_RULE_B", "SYNTHETIC_RULE_C"]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def markers(messages):
    return {scope: [rule for rule in RULES if any(rule in json.dumps(message) for message in messages
            if (message.get("role") == "system") is system)] for scope, system in (("system", True), ("history", False))}


class Provider(BaseHTTPRequestHandler):
    phase = 1
    calls = []
    parents = Counter()
    child_id = None

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/v1/chat/completions"
        tools = [tool["function"]["name"] for tool in body.get("tools", [])]
        parent = self.headers.get("x-opencode-parent-session-id")
        self.calls.append({"primary": bool(tools), "child": bool(parent),
                           "session_id": self.headers.get("x-opencode-session-id"), "parent_id": parent,
                           "body_sha256": digest(body), "model": body.get("model"), "rules": markers(body["messages"]),
                           "credential_matches": self.headers.get("Authorization") == "Bearer synthetic-revision-grant",
                           "prior_turn": "PHASE_ONE_PARENT" in json.dumps(body) or "PHASE_ONE_CHILD" in json.dumps(body)})
        action = bool(tools) and not parent and self.parents[self.phase] == 0
        if tools and not parent:
            self.parents[self.phase] += 1
        message = {"role": "assistant", "content": "Synthetic acknowledgment."}
        if action:
            arguments = {"agent": "explore", "description": "Synthetic revision child", "background": False,
                         "prompt": ("PHASE_ONE_CHILD" if self.phase == 1 else f"PHASE_{self.phase}_CHILD") + ". Acknowledge without tools."}
            if self.child_id:
                arguments["sessionID"] = self.child_id
            message = {"role": "assistant", "content": None, "tool_calls": [{"index": 0, "id": f"call_{self.phase}",
                       "type": "function", "function": {"name": "subagent", "arguments": json.dumps(arguments)}}]}
        stream = body.get("stream")
        response = {"id": "fixture", "object": "chat.completion.chunk" if stream else "chat.completion", "model": "fixture-coder",
                    "choices": [{"index": 0, "delta" if stream else "message": message, "finish_reason": "tool_calls" if action else "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        data = json.dumps(response).encode()
        if stream:
            data = b"data: " + data + b"\n\ndata: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def revision_control(binary, provider):
    with tempfile.TemporaryDirectory(prefix="keeplane-rule-revisions-") as directory:
        root = Path(directory)
        audit, rule_file = root / "hooks.jsonl", root / "rule.txt"
        environment = {"PATH": os.defpath, "OPENCODE_PASSWORD": "synthetic-resident-password",
                       "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_DISABLE_FFF": "1", "OPENCODE_CONFIG_PROJECT_DISABLE": "1"}
        for name, child in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                            ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"), ("TMPDIR", "tmp")):
            (root / child).mkdir(mode=0o700)
            environment[name] = str(root / child)
        (root / "config/opencode").mkdir()
        (root / "config/opencode/opencode.json").write_text('{"update":"disable"}')
        plugin = Path(__file__).resolve().parents[1] / "fixtures/cli_child_hook_plugin"
        config = {"providers": {"keeplane": {"package": "@opencode/ai/providers/openai-compatible",
                  "settings": {"baseURL": f"http://127.0.0.1:{provider.server_port}/v1", "apiKey": "synthetic-revision-grant"},
                  "models": {"fixture-coder": {"name": "Synthetic", "limit": {"context": 32000, "output": 1024}}}}},
                  "model": "keeplane/fixture-coder", "share": "disabled", "snapshots": False,
                  "plugins": [{"package": str(plugin), "options": {"audit": str(audit), "instructionFile": str(rule_file)}}]}
        process, log, endpoint = None, None, None
        auth = {"Authorization": "Basic " + base64.b64encode(b"opencode:synthetic-resident-password").decode()}

        def api(path):
            with urlopen(Request(endpoint + path, headers=auth), timeout=2) as response:
                return json.load(response)

        def stop():
            nonlocal process, log
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
                process = None
                log.close()

        def start(phase):
            nonlocal process, log, endpoint
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
            endpoint = f"http://127.0.0.1:{port}"
            environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
            log = (root / f"server-{phase}.log").open("w")
            process = subprocess.Popen([binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                       env=environment, cwd=root, stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                try:
                    api("/api/mcp")
                    return
                except (URLError, TimeoutError):
                    time.sleep(0.03)
            raise AssertionError("Resident startup deadline exceeded")

        parent_id, child_id = None, None
        try:
            for phase in (1, 2, 3, 4):
                Provider.phase = phase
                if phase < 4:
                    rule_file.write_text(RULES[phase - 1] + "\n")
                else:
                    config.pop("plugins")
                if phase in (1, 3, 4):
                    stop()
                    start(phase)
                before = len(Provider.calls)
                old_hooks = len(audit.read_text().splitlines()) if audit.exists() else 0
                command = [binary, "run", "--server", endpoint, "--auto", "--format", "json", "--model", "keeplane/fixture-coder"]
                if parent_id:
                    command += ["--session", parent_id]
                command += [("PHASE_ONE_PARENT" if phase == 1 else f"PHASE_{phase}_PARENT") + ". Delegate an acknowledgment to explore."]
                result = subprocess.run(command, env=environment, cwd=root, capture_output=True, text=True, timeout=20)
                assert result.returncode == 0, "Native continuation control failed"
                rows = [row for row in Provider.calls[before:] if row["primary"]]
                assert [row["child"] for row in rows] == [False, True, False]
                if phase == 1:
                    parent_id, child_id = rows[0]["session_id"], rows[1]["session_id"]
                    Provider.child_id = child_id
                assert parent_id != child_id
                assert all(row["session_id"] == (child_id if row["child"] else parent_id) for row in rows)
                assert rows[1]["parent_id"] == parent_id
                assert all(row["credential_matches"] and row["model"] == "fixture-coder" for row in rows)
                if phase > 1:
                    assert all(row["prior_turn"] for row in rows)
                expected = [RULES[phase - 1]] if phase < 4 else []
                assert all(row["rules"] == {"system": expected, "history": []} for row in rows)
                hooks = [json.loads(line) for line in audit.read_text().splitlines()[old_hooks:]] if audit.exists() else []
                if phase < 4:
                    http = [row for row in hooks if row["event"] == "http.request"]
                    assert Counter(row["body_sha256"] for row in http) == Counter(row["body_sha256"] for row in Provider.calls[before:])
                    assert all(row["headers_preserved"] and row["remainder_preserved"] for row in http)
                    assert [row["revision"] for row in hooks if row["event"] == "context"] == expected * 3
                else:
                    assert not hooks
                for session_id in (parent_id, child_id):
                    saved = json.dumps(api("/api/session/" + session_id + "/context")["data"])
                    assert not any(rule in saved for rule in RULES)
        finally:
            stop()


def native_rule_revisions(binary):
    assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    Provider.calls, Provider.parents, Provider.child_id = [], Counter(), None
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        revision_control(binary, provider)
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=2)


def test_rule_revisions_and_native_session_resume():
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime")
    native_rule_revisions(binary)


if __name__ == "__main__":
    native_rule_revisions(os.environ["KEEPLANE_OPENCODE_V2_BIN"])
