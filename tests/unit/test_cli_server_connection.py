from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from types import SimpleNamespace
import uuid

import pytest

from components.cli.server_connection import ConnectionError, LIMIT, models, main, logout
from components.cli import session_logout
from components.cli import account_session
from components.cli.credential_profile import Credential, ProfileError, opened
from components.cli.server_connection import account, origin


@pytest.fixture
def server():
    state = SimpleNamespace(project=str(uuid.uuid4()), requests=[], status=200, payload=None, location=None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.requests.append((self.path, self.headers.get("Authorization"), self.headers.get("Cookie"), self.command))
            payload = state.payload if state.payload is not None else json.dumps({"project_id": state.project, "models": [{"id": "coder-b"}, {"id": "coder-a"}]}).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            if state.location:
                self.send_header("Location", state.location)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_DELETE(self):
            self.do_GET()

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


def test_project_catalog_uses_only_explicit_bearer(server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    result = models(server.url, uuid.UUID(server.project).hex, "synthetic-session")
    assert result == {"project_id": server.project, "models": [{"id": "coder-a"}, {"id": "coder-b"}]}
    assert server.requests == [(f"/api/runtime/projects/{server.project}/models", "Bearer synthetic-session", None, "GET")]


@pytest.mark.parametrize("status", [401, 403, 503, 500])
def test_errors_do_not_export_server_bodies(server, status):
    server.status, server.payload = status, b'{"error":"SECRET_PROVIDER_KEY synthetic-session"}'
    with pytest.raises(ConnectionError) as error:
        models(server.url, server.project, "synthetic-session")
    assert "SECRET" not in str(error.value) and "synthetic-session" not in str(error.value)


def test_redirect_is_not_followed(server):
    server.status, server.location = 302, server.url + "/other"
    with pytest.raises(ConnectionError):
        models(server.url, server.project, "synthetic-session")
    assert len(server.requests) == 1


@pytest.mark.parametrize("payload", [b"not JSON", b"[]", b'{"project_id":"different","models":[]}',
    b'{"project_id":"same","models":[{"id":"a","key":"SECRET"}]}'])
def test_invalid_catalog_is_rejected(server, payload):
    server.payload = payload.replace(b'"same"', json.dumps(server.project).encode())
    with pytest.raises(ConnectionError, match="invalid model catalog"):
        models(server.url, server.project, "synthetic-session")


def test_duplicate_and_oversized_catalogs_are_rejected(server):
    for payload in (json.dumps({"project_id": server.project, "models": [{"id": "a"}, {"id": "a"}]}).encode(), b"x" * (LIMIT + 1)):
        server.payload = payload
        with pytest.raises(ConnectionError):
            models(server.url, server.project, "synthetic-session")


@pytest.mark.parametrize("origin", ["http://internal.example", "https://user:key@internal.example", "https://internal.example/?key=SECRET", "https://internal.example/other"])
def test_unsafe_server_is_rejected_before_network(origin):
    with pytest.raises(ConnectionError):
        models(origin, str(uuid.uuid4()), "synthetic-session")


def test_command_uses_environment_without_saving_or_echoing_it(server, monkeypatch, capsys):
    monkeypatch.setenv("KEEPLANE_SESSION_CREDENTIAL", "synthetic-session")
    monkeypatch.setattr("sys.argv", ["server_connection", "--server", server.url, "--project", server.project])
    assert main() == 0
    assert "synthetic-session" not in capsys.readouterr().out


def test_logout_revokes_only_explicit_session(server, monkeypatch, capsys):
    server.status, server.payload = 204, b""
    monkeypatch.setenv("KEEPLANE_SESSION_CREDENTIAL", "synthetic-session")
    monkeypatch.setattr("sys.argv", ["session_logout", "--server", server.url])
    assert session_logout.main() == 0
    assert server.requests == [("/api/runtime/session", "Bearer synthetic-session", None, "DELETE")]
    output = capsys.readouterr().out
    assert "revoked" in output and "synthetic-session" not in output


@pytest.mark.parametrize("status", [200, 302, 401, 403, 503])
def test_logout_does_not_report_success_on_refusal_or_unknown_result(server, status):
    server.status, server.payload = status, b'{"error":"SECRET synthetic-session"}'
    with pytest.raises(ConnectionError) as error:
        logout(server.url, "synthetic-session")
    assert "SECRET" not in str(error.value) and "synthetic-session" not in str(error.value)


@pytest.mark.parametrize("status,removed", [(204, True), (401, True), (503, False), (302, False)])
def test_profile_logout_retains_credentials_on_ambiguous_failure(server, tmp_path, status, removed):
    path = tmp_path / "profile"
    credential = Credential(server.url, str(uuid.uuid4()), "kpc_" + "a" * 43, "r" * 32)
    with opened(path, create=True) as profile:
        profile.save(credential)
    server.status, server.payload = status, b""
    if removed:
        assert "removed" in account_session.run("logout", path)
    else:
        with pytest.raises(ConnectionError):
            account_session.run("logout", path)
    assert (path / "credential.json").exists() is not removed
    assert server.requests == [("/api/runtime/session", "Bearer " + credential.access_token, None, "DELETE")]


def test_profile_whoami_checks_current_actor_and_forget_is_local(server, tmp_path):
    path, actor = tmp_path / "profile", str(uuid.uuid4())
    credential = Credential(server.url, actor, "kpc_" + "a" * 43, "r" * 32)
    with opened(path, create=True) as profile:
        profile.save(credential)
    server.payload = json.dumps({"id": actor, "username": "developer", "role": "admin"}).encode()
    assert json.loads(account_session.run("whoami", path))["role"] == "admin"
    server.payload = server.payload.replace(actor.encode(), str(uuid.uuid4()).encode())
    with pytest.raises(ProfileError, match="account changed"):
        account_session.run("whoami", path)
    count = len(server.requests)
    assert "not requested" in account_session.run("forget", path)
    assert len(server.requests) == count
    assert not (path / "credential.json").exists()


@pytest.mark.parametrize("body", [{"id": "invalid", "username": "developer", "role": "developer"},
                                  {"id": str(uuid.uuid4()), "username": "developer", "role": "root"},
                                  {"id": str(uuid.uuid4()), "username": "developer", "role": "admin", "token": "SECRET"}])
def test_account_response_requires_exact_contract(server, body):
    server.payload = json.dumps(body).encode()
    with pytest.raises(ConnectionError, match="invalid account"):
        account(server.url, "synthetic-session")


def test_issuer_normalization():
    assert origin("https://KEEPPlane.example:443/") == "https://keepplane.example"
    assert origin("http://[::1]:8080") == "http://[::1]:8080"


def test_profile_command_never_prints_saved_credentials(server, tmp_path, monkeypatch, capsys):
    path, actor = tmp_path / "profile", str(uuid.uuid4())
    credential = Credential(server.url, actor, "kpc_" + "a" * 43, "r" * 32)
    with opened(path, create=True) as profile:
        profile.save(credential)
    server.payload = json.dumps({"id": actor, "username": credential.access_token, "role": "developer"}).encode()
    monkeypatch.setattr("sys.argv", ["account_session", "whoami", "--profile", str(path)])
    assert account_session.main() == 0
    output = capsys.readouterr()
    assert credential.access_token not in output.out + output.err
    assert credential.refresh_token not in output.out + output.err
    assert "[redacted]" in output.out
    server.status = 503
    assert account_session.main() == 1
    assert "temporarily unavailable" in capsys.readouterr().err
    assert (path / "credential.json").exists()
