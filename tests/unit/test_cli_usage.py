"""Spec 009 ST31: report each turn's usage and show the developer their own.

The plain-English cases are in cli-usage-cases.md next to this file.
"""

import gzip
import http.client
import json
import socket
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest

from components.cli import keeplane, opencode_adapter, usage, usage_relay
from components.cli.credential_profile import Credential, opened

GRANT = "kpc_" + "g" * 43
USAGE = {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15,
    "prompt_tokens_details": {"cached_tokens": 4},
    "completion_tokens_details": {"reasoning_tokens": 2},
}


class Gateway(BaseHTTPRequestHandler):
    """A stand-in gateway; each test sets how it answers."""

    protocol_version = "HTTP/1.1"
    seen: ClassVar[list] = []
    mode = "stream"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).seen.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        mode = type(self).mode
        if mode == "refuse":
            self.answer(401, b'{"error":"no"}', "application/json")
        elif mode == "whole":
            self.answer(
                200,
                json.dumps({"choices": [], "usage": USAGE}).encode(),
                "application/json",
            )
        elif mode == "whole-no-usage":
            self.answer(200, b'{"choices":[]}', "application/json")
        elif mode == "gzip":
            payload = gzip.compress(json.dumps({"usage": USAGE}).encode())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            # Streamed in chunks, like an OpenAI-compatible server: the usage
            # chunk comes last, split across two writes.
            events = [b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n']
            if mode == "stream":
                final = json.dumps({"choices": [], "usage": USAGE}).encode()
                events += [b"data: " + final[:20], final[20:] + b"\n\n"]
            elif mode == "stream-running":
                for prompt, completion in ((10, 1), (10, 5)):
                    events.append(
                        b"data: "
                        + json.dumps(
                            {
                                "choices": [],
                                "usage": {
                                    "prompt_tokens": prompt,
                                    "completion_tokens": completion,
                                },
                            }
                        ).encode()
                        + b"\n\n"
                    )
            events.append(b"data: [DONE]\n\n")
            if mode == "stall":
                events = events[:1]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for event in events:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(event), event))
                self.wfile.flush()
            if mode == "stall":
                time.sleep(20)  # A model still answering when the turn ends.
            self.wfile.write(b"0\r\n\r\n")

    def answer(self, status, payload, kind):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def gateway():
    Gateway.seen, Gateway.mode = [], "stream"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{server.server_port}/v1", port=server.server_port
    )
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def call(
    relay_url, model="coder", *, path="/chat/completions", headers=None, body=None
):
    """What the runtime does: one model request to its provider address."""
    url = urlsplit(relay_url)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
    payload = (
        body
        if body is not None
        else json.dumps(
            {
                "model": model,
                "stream": True,
                "messages": [{"role": "user", "content": "x"}],
            }
        ).encode()
    )
    connection.request(
        "POST",
        url.path + path,
        payload,
        {
            "Authorization": "Bearer " + GRANT,
            "Content-Type": "application/json",
            "X-Keeplane-Project-ID": "project",
            **(headers or {}),
        },
    )
    answer = connection.getresponse()
    data = answer.read()
    connection.close()
    return answer.status, data


# USE-01 The relay passes every request and answer through unchanged and
# counts the usage in each answer, per model, streamed or not.
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("stream", {"input_tokens": 10, "output_tokens": 5}),
        ("whole", {"input_tokens": 10, "output_tokens": 5}),
        ("stream-running", {"input_tokens": 10, "output_tokens": 5}),
    ],
)
def test_use_01_relay_counts_each_answer(gateway, mode, expected):
    Gateway.mode = mode
    with usage_relay.Relay(gateway.url) as relay:
        assert opencode_adapter.relay_address(relay.url)
        assert relay.url.endswith("/v1")
        status, data = call(relay.url)
        assert status == 200
        if mode.startswith("stream"):
            assert data.endswith(b"data: [DONE]\n\n")
        status, _ = call(relay.url, "large")
        relay.close()
        counts = relay.usage()
    one = {**expected, "requests": 1, "requests_without_usage": 0}
    assert counts == {"coder": one, "large": one}
    # The request reached the gateway as it was sent, with the runtime's own
    # grant and headers, and no other credential.
    row = Gateway.seen[0]
    assert row["path"] == "/v1/chat/completions"
    assert json.loads(row["body"])["model"] == "coder"
    assert row["headers"]["Authorization"] == "Bearer " + GRANT
    assert row["headers"]["X-Keeplane-Project-ID"] == "project"
    assert row["headers"]["Host"] == f"127.0.0.1:{gateway.port}"
    assert row["headers"]["Accept-Encoding"] == "identity"
    assert relay.upstreams == [("127.0.0.1", gateway.port)] * 2


# USE-02 An answer without usage, or one the relay can't read, counts as a
# request without tokens; a refused request isn't counted; an unreachable
# gateway gives the runtime an error.
def test_use_02_requests_without_usage_and_refusals(gateway):
    with usage_relay.Relay(gateway.url) as relay:
        for mode in ("stream-none", "whole-no-usage", "gzip"):
            Gateway.mode = mode
            assert call(relay.url)[0] == 200
        Gateway.mode = "refuse"
        assert call(relay.url)[0] == 401
        # No JSON model name: passed through, not counted.
        Gateway.mode = "whole"
        assert call(relay.url, body=b"not json")[0] == 200
        relay.close()
        assert relay.usage() == {
            "coder": {
                "input_tokens": 0,
                "output_tokens": 0,
                "requests": 3,
                "requests_without_usage": 3,
            }
        }
    with socket.socket() as spare:
        spare.bind(("127.0.0.1", 0))
        closed = spare.getsockname()[1]
    with usage_relay.Relay(f"http://127.0.0.1:{closed}/v1") as relay:
        status, data = call(relay.url)
        assert status == 502 and b"could not reach the gateway" in data
        relay.close()
        assert relay.usage() == {}


# USE-02 A turn that ends while an answer is still streaming doesn't hold the
# CLI up: the relay stops within its bound and counts that call without tokens.
def test_use_02_a_stalled_answer_does_not_hold_the_turn(gateway):
    Gateway.mode = "stall"
    with usage_relay.Relay(gateway.url) as relay:
        url = urlsplit(relay.url)
        connection = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
        connection.request(
            "POST",
            url.path + "/chat/completions",
            json.dumps({"model": "coder", "stream": True}).encode(),
            {"Authorization": "Bearer " + GRANT},
        )
        answer = connection.getresponse()
        assert answer.read1(1024).startswith(b"data: ")
        connection.close()  # The runtime has gone.
        started = time.monotonic()
        relay.close(wait=0.2)
        assert time.monotonic() - started < 3
        assert relay.usage() == {
            "coder": {
                "input_tokens": 0,
                "output_tokens": 0,
                "requests": 1,
                "requests_without_usage": 1,
            }
        }


# USE-03 The relay only takes the gateway's own paths and only listens on
# 127.0.0.1; it refuses a gateway address with credentials.
def test_use_03_relay_scope(gateway):
    with usage_relay.Relay(gateway.url) as relay:
        connection = http.client.HTTPConnection("127.0.0.1", urlsplit(relay.url).port)
        connection.request(
            "POST", "/other/chat/completions", b"{}", {"Content-Length": "2"}
        )
        assert connection.getresponse().status == 404
        connection.close()
        assert relay.server.server_address[0] == "127.0.0.1"
    assert all(row["path"].startswith("/v1/") for row in Gateway.seen)
    with pytest.raises(usage_relay.RelayError):
        usage_relay.Relay("https://user:secret@gateway.test/v1")


# USE-04 The settings check takes only a loopback relay address.
@pytest.mark.parametrize(
    "address,valid",
    [
        ("http://127.0.0.1:41234/v1", True),
        ("http://127.0.0.1:41234", True),
        ("https://127.0.0.1:41234/v1", False),
        ("http://localhost:41234/v1", False),
        ("http://127.0.0.2:41234/v1", False),
        ("http://[::1]:41234/v1", False),
        ("http://127.0.0.1/v1", False),
        ("http://127.0.0.1:41234/v1/", False),
        ("http://127.0.0.1:41234/v1?x=1", False),
        ("http://user@127.0.0.1:41234/v1", False),
        ("https://gateway.test/v1", False),
        (None, False),
    ],
)
def test_use_04_only_a_loopback_relay(address, valid):
    assert opencode_adapter.relay_address(address) is valid


# USE-05 A turn's settings point the runtime at its relay, and the turn's
# counts come back with the result.
def test_use_05_turn_goes_through_the_relay(gateway, tmp_path, monkeypatch):
    seen = {}

    def version(command, **options):
        return subprocess.CompletedProcess(command, 0, "opencode v2.0.27\n", "")

    def turn(command, **options):
        config = json.loads(options["env"]["OPENCODE_CONFIG_CONTENT"])
        seen["base"] = config["providers"]["keeplane"]["settings"]["baseURL"]
        for _ in range(3):
            call(seen["base"])
        return subprocess.CompletedProcess(command, 0, "", "")

    binary = tmp_path / "runtime"
    binary.touch()
    monkeypatch.setattr(opencode_adapter.subprocess, "run", version)
    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)
    result = opencode_adapter.run(
        str(binary), str(tmp_path), gateway.url, "coder", "Fix it.", GRANT
    )
    assert opencode_adapter.relay_address(seen["base"])
    assert result.usage == {
        "coder": {
            "input_tokens": 30,
            "output_tokens": 15,
            "requests": 3,
            "requests_without_usage": 0,
        }
    }
    # The relay is gone once the turn ends.
    with pytest.raises(OSError):
        call(seen["base"])


class Server(BaseHTTPRequestHandler):
    """A stand-in Keeplane server for the usage routes."""

    state = None

    def log_message(self, *args):
        pass

    def do_GET(self):
        state = type(self).state
        state.calls.append(("GET", self.path, None))
        url = urlsplit(self.path)
        if url.path == "/api/runtime/session":
            self.respond(
                state.status,
                {"id": state.actor, "username": "developer", "role": "developer"},
            )
            return
        zone = parse_qs(url.query).get("tz", [None])[0]
        if state.status != 200:
            self.respond(state.status, {"error": "x"})
        elif zone is not None and zone in state.unknown_zones:
            self.respond(400, {"error": "Unknown time zone"})
        else:
            self.respond(200, state.answer)

    def do_POST(self):
        state = type(self).state
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        state.calls.append(("POST", self.path, body))
        if self.path == "/api/runtime/usage":
            self.respond(state.report_status, b"")
            return
        self.respond(200, {"project_id": body["project_id"], "name": "Server original"})

    def respond(self, status, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def period(
    input_tokens=0, output_tokens=0, requests=0, without=0, cost=None, partial=False
):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "requests": requests,
        "requests_without_usage": without,
        "estimated_cost": cost,
        "cost_partial": partial,
    }


ANSWER = {
    "time_zone": "Europe/Berlin",
    "today": "2026-11-09",
    "month": "2026-11",
    "price_list": {"date": "2026-11-03", "currency": "USD"},
    "models": [
        {
            "model": "cloud",
            "cost_status": "estimate",
            "today": period(2000, 500, 7, 1, "0.003500"),
            "this_month": period(1_250_000, 210_000, 31, 3, "4.567890"),
        },
        {
            "model": "local",
            "cost_status": "local",
            "today": period(1200, 300, 2),
            "this_month": period(1200, 300, 2),
        },
        {
            "model": "unpriced",
            "cost_status": "no_list_price",
            "today": period(),
            "this_month": period(40, 10, 1, 1),
        },
    ],
}


@pytest.fixture
def server(tmp_path):
    state = SimpleNamespace(
        actor=str(uuid.uuid4()),
        calls=[],
        status=200,
        report_status=204,
        answer=json.loads(json.dumps(ANSWER)),
        unknown_zones=set(),
        access="kpc_" + "a" * 43,
        refresh="r" * 32,
    )
    Server.state = state
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    state.issuer = f"http://127.0.0.1:{http_server.server_port}"
    state.path = tmp_path / "profile"
    state.path.mkdir(mode=0o700)
    with opened(state.path) as profile:
        profile.save(Credential(state.issuer, state.actor, state.access, state.refresh))
    yield state
    http_server.shutdown()
    http_server.server_close()
    thread.join(timeout=5)


def keeplane_usage(monkeypatch, server, *extra):
    monkeypatch.setattr(
        "sys.argv", ["keeplane", "usage", "--profile", str(server.path), *extra]
    )
    return keeplane.main()


TABLE = """\
Your usage for today, 9 November 2026, and this month, November 2026.

Model     Period      Input tokens  Output tokens  Estimated cost
cloud     Today              2,000            500  $0.0035
          This month     1,250,000        210,000  $4.57
local     Today              1,200            300  —
          This month         1,200            300  —
unpriced  Today                  0              0  no list price
          This month            40             10  no list price

Costs are estimates from each provider's list price (price list of 3 November 2026), in US dollars.
cloud: 3 requests didn't report tokens, so its totals may be low.
unpriced: 1 request didn't report tokens, so its totals may be low.
"""


# USE-06 `keeplane usage` shows each model's tokens and cost for today and
# this month: an estimate in dollars with the label and the list's date, "—"
# for a local model and "no list price" for a cloud model with no price.
def test_use_06_usage_table(server, monkeypatch, capsys):
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert keeplane_usage(monkeypatch, server) == 0
    assert capsys.readouterr().out == TABLE
    assert server.calls == [("GET", "/api/runtime/usage?tz=Europe%2FBerlin", None)]


# USE-07 The time zone: the machine's, or UTC with "(UTC)" when it can't be
# read or the server doesn't know it.
def test_use_07_time_zone_fallback(server, monkeypatch, capsys):
    monkeypatch.setattr(usage, "machine_time_zone", lambda: None)
    assert keeplane_usage(monkeypatch, server) == 0
    out = capsys.readouterr().out
    assert out.startswith(
        "Your usage for today, 9 November 2026, and this month, November 2026 (UTC).\n"
    )
    assert server.calls == [("GET", "/api/runtime/usage", None)]
    server.calls.clear()
    server.unknown_zones = {"Mars/Base"}
    monkeypatch.setattr(usage, "machine_time_zone", lambda: "Mars/Base")
    assert keeplane_usage(monkeypatch, server) == 0
    assert "November 2026 (UTC).\n" in capsys.readouterr().out
    assert [row[1] for row in server.calls] == [
        "/api/runtime/usage?tz=Mars%2FBase",
        "/api/runtime/usage",
    ]


@pytest.mark.parametrize(
    "environ,link,named,expected",
    [
        ({"TZ": "America/New_York"}, None, None, "America/New_York"),
        ({"TZ": ":Asia/Kolkata"}, None, None, "Asia/Kolkata"),
        ({"TZ": "/usr/share/zoneinfo/Asia/Kathmandu"}, None, None, "Asia/Kathmandu"),
        ({}, "/usr/share/zoneinfo/Europe/Berlin", None, "Europe/Berlin"),
        ({}, "/var/db/timezone/zoneinfo/America/St_Johns", None, "America/St_Johns"),
        (
            {},
            "/usr/share/zoneinfo/posix/Australia/Adelaide",
            None,
            "Australia/Adelaide",
        ),
        ({}, None, "Europe/Lisbon\n", "Europe/Lisbon"),
        ({"TZ": "EST5EDT,M3.2.0,M11.1.0"}, None, None, None),
        ({}, None, None, None),
    ],
)
def test_use_07_machine_time_zone(tmp_path, environ, link, named, expected):
    localtime = tmp_path / "localtime"
    if link:
        target = tmp_path / link.lstrip("/")
        target.parent.mkdir(parents=True)
        target.touch()
        localtime.symlink_to(target)
    timezone_file = tmp_path / "timezone"
    if named:
        timezone_file.write_text(named)
    assert usage.machine_time_zone(environ, localtime, timezone_file) == expected


# USE-08 Notes below the table: a cost that leaves some tokens out, nothing
# used yet, and no label when nothing has a cost.
def test_use_08_notes_and_empty_state():
    partial = json.loads(json.dumps(ANSWER))
    partial["models"] = partial["models"][:1]
    partial["models"][0]["today"]["cost_partial"] = True
    text = usage.table(partial)
    assert text.endswith(
        "cloud: some of its tokens couldn't be priced, so its cost may be low."
    )
    local_only = json.loads(json.dumps(ANSWER))
    local_only["models"] = local_only["models"][1:2]
    assert "Costs are estimates" not in usage.table(local_only)
    empty = {**ANSWER, "models": []}
    assert usage.table(empty, utc=True) == (
        "Your usage for today, 9 November 2026, and this month, November 2026 (UTC)."
        "\n\nYou haven't used any models this month."
    )
    assert [
        usage.dollars(value)
        for value in (
            "0.000000",
            "0.000012",
            "0.010000",
            "0.999999",
            "1.005000",
            "1234.5",
        )
    ] == ["$0.00", "$0.000012", "$0.01", "$0.999999", "$1.01", "$1,234.50"]


# USE-09 Only my own usage: the command has no option for another developer,
# and the request names nobody.
def test_use_09_only_my_own_usage(server, monkeypatch, capsys):
    for option in ("--account", "--user", "--developer", "--all"):
        with pytest.raises(SystemExit):
            keeplane_usage(monkeypatch, server, option, "someone")
    capsys.readouterr()
    monkeypatch.setattr(usage, "machine_time_zone", lambda: "UTC")
    assert keeplane_usage(monkeypatch, server) == 0
    assert [row[1] for row in server.calls] == ["/api/runtime/usage?tz=UTC"]


# USE-10 Signed out, an expired sign-in, an older server and a bad answer.
def test_use_10_sign_in_and_server_problems(server, monkeypatch, capsys):
    monkeypatch.setattr(usage, "machine_time_zone", lambda: None)
    server.status = 401
    assert keeplane_usage(monkeypatch, server) == 1
    assert capsys.readouterr().err == (
        "Your Keeplane sign-in has expired. Run `keeplane login` to sign in again.\n"
    )
    server.status = 404
    assert keeplane_usage(monkeypatch, server) == 1
    assert capsys.readouterr().err == (
        "This Keeplane server doesn't show usage yet. Ask your admin to update it.\n"
    )
    server.status = 200
    for broken in (
        {"models": []},
        {**ANSWER, "models": [{**ANSWER["models"][1], "cost_status": "estimate"}]},
        {**ANSWER, "models": [{**ANSWER["models"][0], "account": "x"}]},
        {**ANSWER, "price_list": {"date": "2026-11-03", "currency": "EUR"}},
    ):
        server.answer = broken
        assert keeplane_usage(monkeypatch, server) == 1
        assert capsys.readouterr().err == "The server returned invalid usage.\n"
    (server.path / "credential.json").unlink()
    server.calls.clear()
    assert keeplane_usage(monkeypatch, server) == 1
    assert capsys.readouterr().err == (
        "You're signed out of Keeplane, so nothing was sent. "
        "Run `keeplane login` to sign in.\n"
    )
    assert server.calls == []


# USE-11 After a turn, one report per model it used; a failed report warns
# and never fails the turn.
def test_use_11_report_after_a_turn(server):
    project = str(uuid.uuid4())
    counts = {
        "coder": {
            "input_tokens": 30,
            "output_tokens": 15,
            "requests": 3,
            "requests_without_usage": 1,
        },
        "large": {
            "input_tokens": 0,
            "output_tokens": 0,
            "requests": 0,
            "requests_without_usage": 0,
        },
    }
    assert usage.report_turn(server.issuer, project, server.access, counts) == ""
    assert server.calls == [
        (
            "POST",
            "/api/runtime/usage",
            {
                "project_id": project,
                "model": "coder",
                "input_tokens": 30,
                "output_tokens": 15,
                "requests": 3,
                "requests_without_usage": 1,
            },
        )
    ]
    assert usage.report_turn(server.issuer, project, server.access, {}) == ""
    for status in (401, 403, 503):
        server.report_status = status
        assert usage.report_turn(server.issuer, project, server.access, counts) == (
            "Keeplane couldn't record this task's usage of coder, so "
            "`keeplane usage` may show less than you used.\n"
        )


def test_use_11_keeplane_code_reports_and_keeps_the_turn(
    server, gateway, tmp_path, monkeypatch, capsys
):
    project = str(uuid.uuid4())
    server.answer = {"project_id": project, "models": [{"id": "coder"}]}

    def version(command, **options):
        return subprocess.CompletedProcess(command, 0, "opencode v2.0.27\n", "")

    def turn(command, **options):
        config = json.loads(options["env"]["OPENCODE_CONFIG_CONTENT"])
        base = config["providers"]["keeplane"]["settings"]["baseURL"]
        call(base)
        call(base)
        return subprocess.CompletedProcess(command, 0, "Coding finished.\n", "")

    binary = tmp_path / "runtime"
    binary.touch()
    directory = tmp_path / "repository"
    directory.mkdir()
    monkeypatch.setattr(opencode_adapter.subprocess, "run", version)
    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)
    monkeypatch.setattr(
        keeplane.coding,
        "chosen_model",
        lambda issuer, project_id, model, credential, notify: model,
    )

    def code():
        monkeypatch.setattr(
            "sys.argv",
            [
                "keeplane",
                "code",
                "--profile",
                str(server.path),
                "--project",
                project,
                "--name",
                "Repo",
                "--model",
                "coder",
                "--runtime",
                str(binary),
                "--gateway",
                gateway.url,
                "--directory",
                str(directory),
                "Fix it.",
            ],
        )
        return keeplane.main()

    assert code() == 0
    assert capsys.readouterr().out == "Coding finished.\n"
    reports = [row[2] for row in server.calls if row[1] == "/api/runtime/usage"]
    assert reports == [
        {
            "project_id": project,
            "model": "coder",
            "input_tokens": 20,
            "output_tokens": 10,
            "requests": 2,
            "requests_without_usage": 0,
        }
    ]
    server.report_status = 503
    assert code() == 0
    captured = capsys.readouterr()
    assert captured.out == "Coding finished.\n"
    assert captured.err.endswith(
        "Keeplane couldn't record this task's usage of coder, "
        "so `keeplane usage` may show less than you used.\n"
    )
    assert server.access not in captured.err
