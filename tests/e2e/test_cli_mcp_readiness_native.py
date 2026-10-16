"""Optional pinned resident MCP control; no model warmup or real provider."""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __name__ != "__main__":
    import pytest

    pytestmark = pytest.mark.optional

BINARY_SHA256 = "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"


def mcp(root):
    """Delay actual discovery until the test observes pending; accept no paths."""
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request["method"]
        if method == "initialize":
            result = {"protocolVersion": request["params"]["protocolVersion"],
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "Synthetic readiness", "version": "1"}}
        elif method == "tools/list":
            (root / "listing").touch()
            deadline = time.monotonic() + 8
            while not (root / "release").exists():
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.01)
            result = {"tools": [{"name": "fixture_write", "description": "Write a synthetic marker",
                                 "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]}
        elif method == "tools/call":
            assert request["params"]["name"] == "fixture_write"
            (root / "called").open("a").write("called\n")
            result = {"content": [{"type": "text", "text": "Synthetic tool completed."}], "isError": False}
        else:
            result = {}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)


class Provider(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/v1/chat/completions"
        assert self.headers.get("Authorization") == "Bearer synthetic-provider-grant"
        names = [tool["function"]["name"] for tool in body.get("tools", [])]
        assert body.get("model") == "fixture-coder"
        self.calls.append(names)
        action = bool(names) and not any(message.get("role") == "tool" for message in body["messages"])
        message = {"role": "assistant", "content": "Synthetic acknowledgment."}
        if action:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "index": 0, "id": "call_probe", "type": "function",
                "function": {"name": "probe_fixture_write", "arguments": "{}"}}]}
        stream = body.get("stream")
        response = {"id": "fixture", "object": "chat.completion.chunk" if stream else "chat.completion",
                    "model": "fixture-coder", "choices": [{"index": 0, "delta" if stream else "message": message,
                    "finish_reason": "tool_calls" if action else "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        payload = json.dumps(response).encode()
        if stream:
            payload = b"data: " + payload + b"\n\ndata: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def resident_control(binary, provider, cycle):
    with tempfile.TemporaryDirectory(prefix="keeplane-mcp-ready-") as directory:
        root = Path(directory)
        environment = {"PATH": os.defpath, "OPENCODE_PASSWORD": "synthetic-resident-password",
                       "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_DISABLE_FFF": "1",
                       "OPENCODE_CONFIG_PROJECT_DISABLE": "1"}
        for name, child in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                            ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"), ("TMPDIR", "tmp")):
            (root / child).mkdir(mode=0o700)
            environment[name] = str(root / child)
        (root / "config/opencode").mkdir()
        (root / "config/opencode/opencode.json").write_text('{"update":"disable"}')
        server = {"type": "local", "command": [sys.executable, "-I", str(Path(__file__).resolve()), "mcp", directory],
                  "codemode": False}
        if cycle == "disabled":
            server["disabled"] = True
        if cycle == "failed":
            server["command"] = ["/nonexistent-keeplane-fixture"]
        config = {"providers": {"keeplane": {"package": "@opencode/ai/providers/openai-compatible",
                  "settings": {"baseURL": f"http://127.0.0.1:{provider.server_port}/v1", "apiKey": "synthetic-provider-grant"},
                  "models": {"fixture-coder": {"name": "Synthetic", "limit": {"context": 32000, "output": 1024}}}}},
                  "model": "keeplane/fixture-coder", "share": "disabled", "snapshots": False, "mcp": {"servers": {"probe": server}}}
        environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}"
        headers = {"Authorization": "Basic " + base64.b64encode(b"opencode:synthetic-resident-password").decode()}

        def status(auth=True):
            with urlopen(Request(endpoint + "/api/mcp", headers=headers if auth else {}), timeout=2) as response:
                return json.load(response)["data"]

        with (root / "server.log").open("w") as log:
            process = subprocess.Popen([binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                       env=environment, cwd=root, stdout=log, stderr=log, start_new_session=True)
            before, pending = len(Provider.calls), False
            try:
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    try:
                        servers = status()
                    except (URLError, TimeoutError):
                        time.sleep(0.03)
                        continue
                    rows = [row for row in servers if row["name"] == "probe"]
                    if not rows:
                        time.sleep(0.03)
                        continue
                    state = rows[0]["status"]["status"]
                    if state == "pending" and (root / "listing").exists():
                        pending = True
                        (root / "release").touch()
                    if state in ("connected", "disabled", "failed"):
                        break
                    time.sleep(0.01)
                else:
                    raise AssertionError("Configured MCP server did not settle before the deadline")
                assert len(Provider.calls) == before
                try:
                    status(False)
                except HTTPError as error:
                    assert error.code == 401
                else:
                    raise AssertionError("Resident endpoint accepted an unauthenticated request")
                if cycle in ("cold", "fresh-resident"):
                    assert state == "connected" and pending
                    result = subprocess.run([binary, "run", "--server", endpoint, "--auto", "--format", "json",
                                             "--model", "keeplane/fixture-coder", "Use the fixture_write MCP tool, then acknowledge."],
                                            env=environment, cwd=root, capture_output=True, text=True, timeout=15)
                    assert result.returncode == 0, "Native coding control failed"
                    requests = [names for names in Provider.calls[before:] if names]
                    assert requests and all("probe_fixture_write" in names for names in requests)
                    assert (root / "called").read_text() == "called\n"
                else:
                    assert state == cycle
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)


def native_readiness(binary):
    assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == BINARY_SHA256
    Provider.calls = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        for cycle in ("cold", "fresh-resident", "disabled", "failed"):
            resident_control(binary, provider, cycle)
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=2)


def test_resident_mcp_without_model_warmup():
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime")
    native_readiness(binary)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        mcp(Path(sys.argv[2]))
    else:
        native_readiness(os.environ["KEEPLANE_OPENCODE_V2_BIN"])
