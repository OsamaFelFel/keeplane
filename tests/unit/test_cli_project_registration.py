from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from types import SimpleNamespace
import uuid

import pytest

from components.cli.project_registration import register, main
from components.cli import project_registration
from components.cli.server_connection import ConnectionError


@pytest.fixture
def server():
    state = SimpleNamespace(project=str(uuid.uuid4()), calls=[], status=200, response=None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.calls.append((self.path, self.headers.get("Authorization"), self.headers.get("Cookie"), data))
            body = state.response if state.response is not None else {"project_id": state.project, "name": "Original server name"}
            payload = json.dumps(body).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{http.server_port}"
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def test_registration_sends_only_explicit_context_and_preserves_server_name(server):
    result = register(server.url, uuid.UUID(server.project).hex, "Requested name", "synthetic-session")
    assert result == {"project_id": server.project, "name": "Original server name"}
    assert server.calls == [("/api/runtime/projects", "Bearer synthetic-session", None,
                             {"project_id": server.project, "name": "Requested name"})]


@pytest.mark.parametrize("status", [400, 401, 503])
def test_registration_failures_never_echo_server_secrets(server, status):
    server.status, server.response = status, {"error": "SECRET synthetic-session"}
    with pytest.raises(ConnectionError) as error:
        register(server.url, server.project, "Project", "synthetic-session")
    assert "SECRET" not in str(error.value) and "synthetic-session" not in str(error.value)


@pytest.mark.parametrize("result", [[], {"project_id": "wrong", "name": "Project"},
                                   {"project_id": "same", "name": "Project", "key": "SECRET"}])
def test_wrong_project_or_extra_metadata_is_rejected(server, result):
    server.response = result
    if isinstance(result, dict) and result.get("project_id") == "same":
        result["project_id"] = server.project
    with pytest.raises(ConnectionError):
        register(server.url, server.project, "Project", "synthetic-session")


@pytest.mark.parametrize("project,name", [("invalid", "Project"), (str(uuid.uuid4()), " "),
                                         (str(uuid.uuid4()), "x" * 121), (str(uuid.uuid4()), "bad\nname")])
def test_invalid_context_stops_before_network(project, name, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid context must not make a network request.")
    monkeypatch.setattr(project_registration, "request", forbidden)
    with pytest.raises(ConnectionError):
        register("http://127.0.0.1:1", project, name, "synthetic-session")


def test_registration_command_prints_only_confirmed_metadata(server, monkeypatch, capsys):
    monkeypatch.setenv("KEEPLANE_SESSION_CREDENTIAL", "synthetic-session")
    monkeypatch.setattr("sys.argv", ["project_registration", "--server", server.url, "--project", server.project, "--name", "Project"])
    assert main() == 0
    output = capsys.readouterr().out
    assert "Original server name" in output and "synthetic-session" not in output
