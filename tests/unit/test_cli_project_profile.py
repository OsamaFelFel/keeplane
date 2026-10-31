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
        choice=None,
        choice_status=200,
        alternatives=[],
        alternatives_status=200,
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
            elif "/model-choice?" in self.path:
                requested = self.path.split("model_id=")[-1]
                value = {
                    "project_id": self.path.split("/")[-2],
                    "requested_model_id": requested,
                    "model_id": requested,
                    "reason": None,
                    **(state.choice or {}),
                }
                status = state.choice_status
            elif "/model-alternatives?" in self.path:
                value = {
                    "project_id": self.path.split("/")[-2],
                    "model_id": self.path.split("model_id=")[-1],
                    "alternatives": state.alternatives,
                }
                status = state.alternatives_status
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
        ("GET", f"/api/runtime/projects/{project}/model-choice?model_id=coder"),
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
        connected.model_ids = ["general"]
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


def native_model(runtime):
    native_command, _ = runtime[1][-1]
    return native_command[native_command.index("--model") + 1]


@pytest.mark.parametrize(
    "reason,text",
    [
        ("missing", "No provider key is added for coder; using general instead. Add one"),
        ("refused", "The provider refused your key for coder; using general instead. Replace it"),
        ("outdated", "saved for an earlier model setup; using general instead. Replace it"),
    ],
)
def test_unusable_own_key_moves_the_task_to_another_allowed_model_and_says_why(
    connected, runtime, monkeypatch, tmp_path, capsys, reason, text
):
    connected.model_ids = ["coder", "general"]
    connected.choice = {"model_id": "general", "reason": reason}
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    assert native_model(runtime) == "keeplane/general"
    output = capsys.readouterr()
    assert output.out == "Coding finished.\n"
    assert text in output.err and "`keeplane keys set --model coder`" in output.err
    assert connected.access not in output.err and connected.refresh not in output.err


def test_usable_key_keeps_the_requested_model_without_a_notice(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    connected.model_ids = ["coder", "general"]
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    assert native_model(runtime) == "keeplane/coder"
    assert capsys.readouterr().err == ""


def test_no_other_allowed_model_fails_with_the_missing_key_message(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    connected.choice = {"model_id": None, "reason": "missing"}
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert not runtime[1]
    error = capsys.readouterr().err
    assert error.startswith("Add or replace your provider key: No provider key is added for coder")
    assert "no other allowed model" in error and "`keeplane keys set --model coder`" in error


def test_an_approved_model_that_is_not_up_stops_with_a_clear_message(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    # Spec 005 ST19 "No approved model is up": nothing is sent anywhere.
    connected.model_ids = ["coder", "general"]
    connected.choice = {"model_id": None, "reason": "unavailable"}
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert not runtime[1]
    error = capsys.readouterr().err
    assert error == (
        "coder is approved for this project but can't be used right now, so nothing "
        "was sent. Choose another model allowed for this project, or ask an admin "
        "to check it in Models and routing.\n"
    )


def test_repository_settings_cannot_change_the_model_or_destination(
    connected, runtime, monkeypatch, tmp_path
):
    # Spec 005 ST19 "The repo can't change it": the repository's own runtime
    # settings and environment point elsewhere, but are never loaded.
    hostile = {
        "model": "direct/unapproved",
        "providers": {"direct": {"settings": {"baseURL": "https://provider.invalid/v1",
                                              "apiKey": "repo-key"},
                                 "models": {"unapproved": {}}}},
    }
    (tmp_path / "opencode.json").write_text(json.dumps(hostile))
    (tmp_path / ".opencode").mkdir()
    (tmp_path / ".opencode" / "opencode.json").write_text(json.dumps(hostile))
    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", json.dumps(hostile))
    monkeypatch.setenv("OPENCODE_MODEL", "direct/unapproved")
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    native_command, options = runtime[1][0]
    environment = options["env"]
    assert native_model(runtime) == "keeplane/coder"
    assert environment["OPENCODE_CONFIG_PROJECT_DISABLE"] == "1"
    assert "OPENCODE_CONFIG" not in environment and "OPENCODE_MODEL" not in environment
    config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == "keeplane/coder" and set(config["providers"]) == {"keeplane"}
    assert config["providers"]["keeplane"]["settings"] == {"baseURL": "https://gateway.test/v1"}
    assert "unapproved" not in json.dumps([native_command, config])
    assert "repo-key" not in json.dumps([native_command, config])


@pytest.mark.parametrize(
    "change",
    [
        {"model_id": "elsewhere", "reason": "missing"},
        {"model_id": "general", "reason": None},
        {"model_id": "coder", "reason": "missing"},
        {"model_id": "general", "reason": "unknown"},
        {"model_id": "general", "reason": "unavailable"},
        {"requested_model_id": "other"},
        {"project_id": str(uuid.uuid4())},
        {"extra": True},
    ],
)
def test_fallback_outside_the_catalog_or_an_invalid_choice_never_starts_the_runtime(
    connected, runtime, monkeypatch, tmp_path, capsys, change
):
    connected.model_ids = ["coder", "general"]
    connected.choice = change
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert not runtime[1]
    assert connected.access not in capsys.readouterr().err


@pytest.mark.parametrize("status,launched", [(404, True), (403, False), (503, False)])
def test_server_without_a_choice_route_keeps_the_gateway_check(
    connected, runtime, monkeypatch, tmp_path, capsys, status, launched
):
    connected.choice_status = status
    connected.choice = {"error": "unused"}
    result = code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path)
    assert (result == 0) is launched and bool(runtime[1]) is launched
    if launched:
        assert native_model(runtime) == "keeplane/coder"


def test_no_models_yet_says_so_and_sends_nothing(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    # Spec 004 ST12: the organization has registered no models yet.
    connected.model_ids = []
    project = str(uuid.uuid4())
    assert code(monkeypatch, connected, runtime, project, tmp_path) == 1
    assert not runtime[1]
    assert [(row[0], row[1]) for row in connected.calls][-1] == (
        "GET", f"/api/runtime/projects/{project}/models"
    )
    assert all("/model-choice" not in row[1] for row in connected.calls)
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith(
        "No models are available for this project yet, so nothing was sent."
    )
    assert connected.access not in output.err and connected.refresh not in output.err


def test_a_model_outside_a_non_empty_catalog_keeps_the_not_allowed_message(
    connected, runtime, monkeypatch, tmp_path, capsys
):
    connected.model_ids = ["general"]
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert not runtime[1]
    assert capsys.readouterr().err == (
        "This model is not currently allowed for the project.\n"
    )


def test_keeplane_sets_no_request_settings_of_its_own(
    connected, runtime, monkeypatch, tmp_path
):
    # Spec 004 ST26: the runtime's own settings, such as temperature, are not
    # replaced or added by Keeplane's generated configuration.
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    config = json.loads(runtime[1][0][1]["env"]["OPENCODE_CONFIG_CONTENT"])
    provider = config["providers"]["keeplane"]
    assert set(provider) == {"package", "env", "settings", "models", "headers"}
    assert provider["settings"] == {"baseURL": "https://gateway.test/v1"}
    assert provider["models"] == {"coder": {"name": "coder"}}
    assert set(config) == {"providers", "model", "share", "snapshots"}
