"""Project commands use only a saved issuer and its current server account."""

import json
import subprocess
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from components.cli import coding, keeplane, opencode_adapter
from components.cli.credential_profile import Credential, opened
from components.cli.session_state import managed


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


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    binary = tmp_path / "runtime"
    binary.touch()
    calls = []

    def version(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "2.0.27", "")

    def turn(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, "Coding finished.\n", "")

    monkeypatch.setattr(opencode_adapter.subprocess, "run", version)
    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)
    return binary, calls


def code(monkeypatch, connected, runtime, project, directory, *extra):
    return command(
        monkeypatch, connected, "code", "--project", project, "--name", "Requested",
        "--model", "coder", "--runtime", str(runtime[0]),
        "--gateway", "https://gateway.test/v1", "--directory", str(directory),
        *extra, "Fix the addition function.",
    )


def test_signed_in_coding_registers_checks_catalog_and_passes_project_context(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    project = str(uuid.uuid4())
    state = tmp_path / "history"
    directory = tmp_path / "repository"
    directory.mkdir()
    assert code(monkeypatch, connected, runtime, project, directory,
                "--state-dir", str(state)) == 0
    assert capsys.readouterr().out == "Coding finished.\n"
    assert [(row[0], row[1]) for row in connected.calls] == [
        ("GET", "/api/runtime/session"), ("POST", "/api/runtime/projects"),
        ("GET", f"/api/runtime/projects/{project}/models"),
    ]
    native_command, options = runtime[1][0]
    environment = options["env"]
    config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
    assert config["providers"]["keeplane"]["headers"] == {"X-Keeplane-Project-ID": project}
    assert config["providers"]["keeplane"]["settings"] == {"baseURL": "https://gateway.test/v1"}
    assert environment["KEEPLANE_RUNTIME_GRANT"] == connected.access
    assert connected.access not in json.dumps(native_command) + json.dumps(config)
    assert options["input"] == "Fix the addition function."
    binding = json.loads((state / "binding.json").read_text())["binding"]
    assert binding["issuer"] == connected.issuer
    assert binding["actor_id"] == connected.actor and binding["project_id"] == project
    assert connected.access not in (state / "binding.json").read_text()
    assert connected.refresh not in json.dumps(environment)
    assert all("Cookie" not in row[2] for row in connected.calls)


@pytest.mark.parametrize("withdrawal", ["actor", "401", "503", "model"])
def test_signed_in_coding_stops_before_runtime_when_current_access_is_unavailable(
    connected, runtime, monkeypatch, tmp_path, capsys, withdrawal
):
    if withdrawal == "actor":
        connected.actor = str(uuid.uuid4())
    elif withdrawal == "model":
        connected.model_ids = []
    else:
        connected.status = int(withdrawal)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert not runtime[1]
    assert len(connected.calls) == (3 if withdrawal == "model" else 1)
    output = capsys.readouterr()
    assert connected.access not in output.out + output.err
    assert connected.refresh not in output.out + output.err


def test_history_allows_fresh_credentials_but_refuses_another_account_or_project(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    directory = tmp_path / "repository"
    directory.mkdir()
    state, project = tmp_path / "history", str(uuid.uuid4())
    assert code(monkeypatch, connected, runtime, project, directory, "--state-dir", str(state)) == 0
    connected.access = "kpc_" + "b" * 43
    with opened(connected.path) as profile:
        profile.save(Credential(connected.issuer, connected.actor, connected.access, connected.refresh))
    assert code(monkeypatch, connected, runtime, project, directory, "--state-dir", str(state)) == 0
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), directory,
                "--state-dir", str(state)) == 1
    connected.actor = str(uuid.uuid4())
    with opened(connected.path) as profile:
        profile.save(Credential(connected.issuer, connected.actor, connected.access, connected.refresh))
    assert code(monkeypatch, connected, runtime, project, directory, "--state-dir", str(state)) == 1
    assert len(runtime[1]) == 2
    assert connected.actor != json.loads((state / "binding.json").read_text())["binding"]["actor_id"]
    output = capsys.readouterr()
    assert connected.access not in output.out + output.err


def test_signed_in_coding_refuses_legacy_history_without_an_account_binding(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    directory, state = tmp_path / "repository", tmp_path / "history"
    directory.mkdir()
    with managed(state, {"directory": str(directory), "gateway": "https://gateway.test/v1",
                         "model": "coder", "version": "2.0.27"}, None):
        pass
    before = (state / "binding.json").read_bytes()
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), directory,
                "--state-dir", str(state)) == 1
    assert not runtime[1] and (state / "binding.json").read_bytes() == before
    assert "securely" in capsys.readouterr().err


@pytest.mark.parametrize("gateway", ["http://remote.test/v1", "https://user:key@remote.test/v1",
                                    "https://gateway.test/v1?key=secret", "https://gateway.test/raw"])
def test_invalid_coding_destination_stops_before_profile_or_network(gateway, tmp_path):
    with pytest.raises((ValueError, coding.ConnectionError)):
        coding.run(tmp_path / "missing", str(uuid.uuid4()), "Project", "coder",
                   tmp_path / "runtime", tmp_path, gateway, "Fix.")


@pytest.mark.parametrize("kind", ["timeout", "terminated", "cancelled"])
def test_coding_exit_status_does_not_print_exception_credentials(
    connected, runtime, monkeypatch, tmp_path, capsys, kind
):
    def turn(*args, **kwargs):
        if kind == "timeout":
            raise subprocess.TimeoutExpired("native", 1, output=connected.access)
        if kind == "terminated":
            raise opencode_adapter.Cancelled(connected.access)
        raise KeyboardInterrupt(connected.refresh)
    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == {
        "timeout": 124, "terminated": 143, "cancelled": 130,
    }[kind]
    output = capsys.readouterr()
    assert connected.access not in output.out + output.err
    assert connected.refresh not in output.out + output.err
