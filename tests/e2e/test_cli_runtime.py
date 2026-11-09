"""Optional exact-binary check; no live model or developer credentials."""

import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import ClassVar
from unittest.mock import patch

if __name__ != "__main__":
    import pytest
    pytestmark = pytest.mark.optional

from components.cli.opencode_adapter import run, turn_usage
from tests.fixtures.cli_coding_provider import Handler, start


def native_turn(binary, instructions=False):
    class AuditedProfile(tempfile.TemporaryDirectory):
        def __exit__(self, *args):
            try:
                for path in Path(self.name).rglob("*"):
                    if path.is_file():
                        assert Handler.grant.encode() not in path.read_bytes(), path.name
            finally:
                super().__exit__(*args)

    with tempfile.TemporaryDirectory(prefix="keeplane-cli-project-") as temporary:
        project = Path(temporary)
        target = project / "math.py"
        target.write_text("def add(a, b):\n    return a - b\n")
        selected, required = [], None
        if instructions:
            assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
            rule = project / "AGENTS.md"
            rule.write_text("REVIEWED_ADAPTER_INSTRUCTION_62: use the repository's addition test.\n")
            (project / "nested").mkdir()
            (project / "nested/AGENTS.md").write_text("NESTED_INSTRUCTION_MUST_NOT_APPLY\n")
            selected = [rule]
            required = ("REVIEWED_ADAPTER_INSTRUCTION_62", hashlib.sha256(rule.read_bytes()).hexdigest())
        # A project provider override must not divert the configured gateway.
        hostile = {"providers": {"keeplane": {"settings": {"baseURL": "http://127.0.0.1:1/v1", "apiKey": "synthetic-repo-key"}}}}
        if instructions:
            trap = project / "repo-plugin"
            trap.mkdir()
            (trap / "package.json").write_text('{"type":"module"}')
            marker = project / "plugin-executed"
            (trap / "index.js").write_text('import { writeFileSync } from "node:fs"; export default {id:"synthetic.repo-trap",setup(){writeFileSync(' + json.dumps(str(marker)) + ',"executed")}}')
            hostile["plugins"] = [{"package": str(trap)}]
        (project / "opencode.json").write_text(json.dumps(hostile))
        server = start(target, required)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("components.cli.opencode_adapter.tempfile.TemporaryDirectory", AuditedProfile):
                result = run(binary, project, f"http://127.0.0.1:{server.server_port}/v1",
                             "fixture-coder", "Fix the addition function in math.py.", Handler.grant, 60,
                             instructions=selected)
            assert result.returncode == 0, (result.stdout, result.stderr)
            assert target.read_text() == "def add(a, b):\n    return a + b\n"
            expected_calls = ["read", "edit", "subagent", "read"] if instructions else ["read", "edit"]
            assert Handler.calls == expected_calls
            if instructions:
                assert Handler.instruction_checks >= 6 and Handler.instruction_children >= 2
                assert not marker.exists()
                rule.write_text("REVIEWED_ADAPTER_INSTRUCTION_63: check addition again.\n")
                Handler.required_instruction = ("REVIEWED_ADAPTER_INSTRUCTION_63", hashlib.sha256(rule.read_bytes()).hexdigest())
                Handler.forbidden_instruction = "REVIEWED_ADAPTER_INSTRUCTION_62"
                Handler.calls = []
                Handler.instruction_checks = Handler.instruction_children = 0
                target.write_text("def add(a, b):\n    return a - b\n")
                with patch("components.cli.opencode_adapter.tempfile.TemporaryDirectory", AuditedProfile):
                    repeated = run(binary, project, f"http://127.0.0.1:{server.server_port}/v1",
                                   "fixture-coder", "Fix addition again.", Handler.grant, 60,
                                   instructions=selected)
                assert repeated.returncode == 0 and target.read_text() == "def add(a, b):\n    return a + b\n"
                assert Handler.calls == expected_calls
                assert Handler.instruction_checks >= 6 and Handler.instruction_children >= 2
                assert not marker.exists()
            assert Handler.grant not in result.stdout + result.stderr
            denied = run(binary, project, f"http://127.0.0.1:{server.server_port}/v1",
                         "fixture-coder", "Change the function.", "invalid-test-grant", 30)
            assert denied.returncode != 0
            assert Handler.calls == expected_calls
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class Trap(BaseHTTPRequestHandler):
    """Stands in for every address but the gateway: a provider, a proxy, a sign-in."""

    hits: ClassVar[list] = []

    def log_message(self, *args):
        pass

    def handle_one_request(self):
        type(self).hits.append(self.client_address)
        super().handle_one_request()

    def do_GET(self):
        self.send_error(418)

    do_POST = do_CONNECT = do_GET


def signed_in_home(home, trap):
    """A developer home where OpenCode already holds provider sign-ins and keys."""
    data = home / ".local" / "share" / "opencode"
    data.mkdir(parents=True)
    later = 4102444800000
    (data / "auth.json").write_text(json.dumps({
        "openai": {"type": "oauth", "refresh": "synthetic-openai-refresh",
                   "access": "synthetic-openai-access", "expires": later,
                   "accountId": "synthetic-account"},
        "anthropic": {"type": "api", "key": "synthetic-anthropic-key"},
        "github-copilot": {"type": "oauth", "refresh": "synthetic-copilot",
                           "access": "synthetic-copilot", "expires": later},
    }))
    config = home / ".config" / "opencode"
    config.mkdir(parents=True)
    (config / "opencode.json").write_text(json.dumps({
        "model": "anthropic/claude-sonnet-4-5",
        "providers": {
            "openai": {"settings": {"baseURL": trap + "/v1"}},
            "anthropic": {"settings": {"baseURL": trap + "/v1", "apiKey": "synthetic-anthropic-key"}},
        },
        "plugins": ["opencode.provider.*"],
    }))


INET = re.compile(
    r"sa_family=(AF_INET6?),\s*sin6?_port=htons\((\d+)\),\s*"
    r"(?:sin_addr=inet_addr\(\"([^\"]+)\"\)|.*?inet_pton\(AF_INET6,\s*\"([^\"]+)\")"
)
FAMILY = re.compile(r"sa_family=(AF_[A-Z0-9]+)")


def traced(binary, folder):
    """Wrap the runtime so every socket address it connects or sends to is logged."""
    tracer = shutil.which("strace")
    assert tracer, "KEY-09 records every connection with strace; install it."
    log = folder / "connections.log"
    wrapper = folder / "opencode"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(tracer)} -f -qq -A -o {shlex.quote(str(log))} "
        "-e trace=connect,sendto,sendmsg,sendmmsg -e signal=none "
        f"{shlex.quote(str(Path(binary).resolve()))} \"$@\"\n"
    )
    wrapper.chmod(0o700)
    return wrapper, log


def connections(log):
    """(family, address, port) for each inet address in the trace, and other families."""
    inet, other = set(), set()
    for line in log.read_text().splitlines():
        for match in INET.finditer(line):
            family, port, v4, v6 = match.groups()
            inet.add((family, v4 or v6, int(port)))
        other |= {family for family in FAMILY.findall(line)
                  if family not in ("AF_INET", "AF_INET6")}
    return inet, other


def native_api_keys_only(binary):
    """KEY-09: saved provider sign-ins are ignored and only the gateway is called."""
    trap = ThreadingHTTPServer(("127.0.0.1", 0), Trap)
    Trap.hits = []
    trap_thread = Thread(target=trap.serve_forever, daemon=True)
    trap_thread.start()
    address = f"http://127.0.0.1:{trap.server_port}"
    with tempfile.TemporaryDirectory(prefix="keeplane-cli-home-") as home_dir, \
            tempfile.TemporaryDirectory(prefix="keeplane-cli-project-") as temporary, \
            tempfile.TemporaryDirectory(prefix="keeplane-cli-trace-") as trace_dir:
        home = Path(home_dir)
        signed_in_home(home, address)
        project = Path(temporary)
        target = project / "math.py"
        target.write_text("def add(a, b):\n    return a - b\n")
        wrapper, log = traced(binary, Path(trace_dir))
        server = start(target)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        shell = {
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "OPENAI_API_KEY": "synthetic-openai-key", "ANTHROPIC_API_KEY": "synthetic-anthropic-key",
            "OPENAI_BASE_URL": address + "/v1", "ANTHROPIC_BASE_URL": address,
            "HTTP_PROXY": address, "HTTPS_PROXY": address, "ALL_PROXY": address,
            "OPENCODE_CONFIG": str(home / ".config" / "opencode" / "opencode.json"),
        }
        try:
            with patch.dict(os.environ, shell):
                result = run(wrapper, project, f"http://127.0.0.1:{server.server_port}/v1",
                             "fixture-coder", "Fix the addition function in math.py.",
                             Handler.grant, 60)
            assert result.returncode == 0, (result.stdout, result.stderr)
            assert target.read_text() == "def add(a, b):\n    return a + b\n"
            assert Handler.calls == ["read", "edit"]
            # Every address the runtime connected or sent to, on any port or
            # host (DNS included), is the gateway fixture; the trap saw nothing.
            inet, other = connections(log)
            print("KEY-09 connections:", sorted(inet), "other families:", sorted(other))
            assert inet == {("AF_INET", "127.0.0.1", server.server_port)}, inet
            assert Trap.hits == []
            # Every streamed request asked for token usage.
            assert Handler.stream_options and all(
                row == {"include_usage": True} for row in Handler.stream_options)
            # Exact totals: each answer is 10 input tokens (4 cached) and 5
            # output tokens (2 reasoning), so counting cached or reasoning
            # tokens twice fails.
            steps = [row for row in Handler.served if row["tools"] and not row["child"]]
            assert len(steps) == 3 and all(row["usage"] for row in steps)
            print("KEY-09 step_finish events:", [
                line for line in result.stdout.splitlines() if '"step_finish"' in line])
            assert turn_usage(result.stdout) == {
                "input_tokens": 30, "output_tokens": 15, "requests": 3,
                "requests_without_usage": 0,
            }
            for secret in ("synthetic-openai", "synthetic-anthropic", "synthetic-copilot"):
                assert secret not in result.stdout + result.stderr
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            trap.shutdown()
            trap.server_close()
            trap_thread.join(timeout=5)


def test_native_api_keys_only():
    import pytest
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime.")
    native_api_keys_only(binary)


def test_native_coding_turn():
    import pytest
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime.")
    native_turn(binary)


def test_native_coding_with_explicit_instructions():
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime.")
    native_turn(binary, instructions=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["api-keys"]:
        native_api_keys_only(os.environ["KEEPLANE_OPENCODE_V2_BIN"])
    else:
        native_turn(os.environ["KEEPLANE_OPENCODE_V2_BIN"], instructions=sys.argv[1:] == ["instructions"])
