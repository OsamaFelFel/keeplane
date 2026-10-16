"""Synthetic model oracle behind the real installed gateway and server key."""

import hashlib
import io
import json
from typing import ClassVar

from tests.fixtures.cli_coding_provider import Handler

RULE = "INSTALLED_CLI_RULE: preserve the addition function's interface."
DIGEST = hashlib.sha256((RULE + "\n").encode()).hexdigest()


class InstalledCliProvider(Handler):
    contacts = 0
    continued = 0
    failures: ClassVar[list[str]] = []

    def details(self):
        return {}

    def respond(self, body):
        return False

    def do_GET(self):
        if self.path != "/fixture/status":
            self.send_error(404)
            return
        raw = json.dumps(
            {
                "contacts": self.contacts,
                "tools": self.calls,
                "continued": self.continued,
                "failures": self.failures,
                **self.details(),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        type(self).contacts += 1
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        self.rfile = io.BytesIO(raw)
        try:
            assert self.headers.get("Authorization") == "Bearer " + self.grant
            assert not any(
                name.lower().startswith(("x-keeplane-", "x-opencode-"))
                or name.lower() in {"cookie", "x-api-key", "x-provider-authorization"}
                for name in self.headers
            )
            body = json.loads(raw)
            if body.get("tools"):
                system = json.dumps(
                    [row for row in body["messages"] if row.get("role") == "system"]
                )
                assert f"SHA-256 {DIGEST})\\n{RULE}" in system
                last = max(
                    index
                    for index, row in enumerate(body["messages"])
                    if row.get("role") == "user"
                )
                resumed = "SECOND_RESUMED_TURN" in json.dumps(body["messages"][last])
                Handler.call_prefix = "second_" if resumed else "first_"
                if resumed:
                    history = body["messages"][:last]
                    assert "FIRST_SAVED_TURN" in json.dumps(history)
                    calls = {
                        call["id"]: call["function"]
                        for row in history
                        for call in row.get("tool_calls", [])
                    }
                    results = {
                        row["tool_call_id"]
                        for row in history
                        if row.get("role") == "tool" and row.get("content")
                    }
                    assert {call["name"] for call in calls.values()} == {"read", "edit"}
                    assert set(calls) <= results
                    for call in calls.values():
                        arguments = json.loads(call["arguments"])
                        assert arguments["path"] == str(self.target)
                        if call["name"] == "edit":
                            assert (
                                arguments["oldString"] == "return a - b"
                                and arguments["newString"] == "return a + b"
                            )
                    type(self).continued += 1
            if self.respond(body):
                return
        except (AssertionError, ValueError, KeyError, TypeError):
            self.failures.append("provider-oracle")
            self.send_error(500, "Synthetic provider oracle failed")
            return
        super().do_POST()
