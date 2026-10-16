"""Project commands use only a saved issuer and its current server account."""

import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from components.cli import keeplane
from components.cli.credential_profile import Credential, opened


@pytest.fixture
def connected(tmp_path):
    state = SimpleNamespace(
        actor=str(uuid.uuid4()),
        calls=[],
        status=200,
        access="kpc_" + "a" * 43,
        refresh="r" * 32,
        model_ids=["coder"],
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.calls.append((self.command, self.path, dict(self.headers), None))
            if self.path == "/api/runtime/session":
                value = {
                    "id": state.actor,
                    "username": "developer",
                    "role": "developer",
                }
                status = state.status
            else:
                value = {
                    "project_id": self.path.split("/")[-2],
                    "models": [{"id": value} for value in state.model_ids],
                }
                status = 200
            self.respond(status, value)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.calls.append((self.command, self.path, dict(self.headers), body))
            self.respond(
                200, {"project_id": body["project_id"], "name": "Server original"}
            )

        def do_DELETE(self):
            state.calls.append((self.command, self.path, dict(self.headers), None))
            self.respond(204, b"")

        def respond(self, status, value):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    state.issuer, state.path = (
        f"http://127.0.0.1:{http.server_port}",
        tmp_path / "profile",
    )
    with opened(state.path, create=True) as profile:
        profile.save(Credential(state.issuer, state.actor, state.access, state.refresh))
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)


def command(monkeypatch, connected, action, *arguments):
    monkeypatch.setattr(
        "sys.argv", ["keeplane", action, "--profile", str(connected.path), *arguments]
    )
    return keeplane.main()


def test_one_entry_point_account_registration_catalog_and_logout(
    connected, monkeypatch, capsys
):
    project = str(uuid.uuid4())
    assert command(monkeypatch, connected, "whoami") == 0
    assert json.loads(capsys.readouterr().out)["id"] == connected.actor
    assert (
        command(
            monkeypatch,
            connected,
            "register-project",
            "--project",
            uuid.UUID(project).hex,
            "--name",
            "Requested",
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "project_id": project,
        "name": "Server original",
    }
    assert command(monkeypatch, connected, "models", "--project", project) == 0
    assert json.loads(capsys.readouterr().out)["models"] == [{"id": "coder"}]
    assert command(monkeypatch, connected, "logout") == 0
    assert (
        "removed" in capsys.readouterr().out
        and not (connected.path / "credential.json").exists()
    )
    assert [(row[0], row[1]) for row in connected.calls] == [
        ("GET", "/api/runtime/session"),
        ("GET", "/api/runtime/session"),
        ("POST", "/api/runtime/projects"),
        ("GET", "/api/runtime/session"),
        ("GET", f"/api/runtime/projects/{project}/models"),
        ("DELETE", "/api/runtime/session"),
    ]
    assert connected.calls[2][3] == {"project_id": project, "name": "Requested"}
    assert all(
        row[2]["Authorization"] == "Bearer " + connected.access
        and "Cookie" not in row[2]
        for row in connected.calls
    )


@pytest.mark.parametrize("withdrawal", ["actor", "401", "503"])
@pytest.mark.parametrize("action", ["register-project", "models"])
def test_changed_or_withdrawn_account_stops_before_project_request(
    connected, monkeypatch, capsys, withdrawal, action
):
    if withdrawal == "actor":
        connected.actor = str(uuid.uuid4())
    else:
        connected.status = int(withdrawal)
    args = ["--project", str(uuid.uuid4())] + (
        ["--name", "Project"] if action == "register-project" else []
    )
    assert command(monkeypatch, connected, action, *args) == 1
    assert len(connected.calls) == 1 and connected.calls[0][1] == "/api/runtime/session"
    output = capsys.readouterr()
    assert (
        connected.access not in output.out + output.err
        and connected.refresh not in output.out + output.err
    )


def test_catalog_output_cannot_export_profile_credentials(
    connected, monkeypatch, capsys
):
    connected.model_ids = [connected.access, connected.refresh]
    assert (
        command(monkeypatch, connected, "models", "--project", str(uuid.uuid4())) == 0
    )
    output = capsys.readouterr()
    assert (
        connected.access not in output.out + output.err
        and connected.refresh not in output.out + output.err
    )
    assert "[redacted]" in output.out
