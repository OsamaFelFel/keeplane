"""Actual HTTP key commands: hidden input, current identity and uncertain writes."""

import io
import json
import sys
import uuid
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from components.cli import keeplane, provider_keys
from components.cli.credential_profile import Credential, opened


@pytest.fixture
def api(tmp_path, monkeypatch):
    state = SimpleNamespace(
        actor=str(uuid.uuid4()),
        access="kpc_" + "a" * 43,
        refresh="kpr_" + "r" * 43,
        calls=[],
        model="provider/model ?&=#",
        stored=False,
        account_status=200,
        write_status=200,
        pending=False,
        response_fault=False,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.calls.append((self.command, self.path, dict(self.headers), None))
            if self.path == "/api/runtime/session":
                self.respond(
                    state.account_status,
                    {"id": state.actor, "username": "developer", "role": "developer"},
                )
            else:
                assert parse_qs(urlsplit(self.path).query) == {
                    "model_id": [state.model]
                }
                self.respond(200, self.metadata())

        def do_PUT(self):
            self.mutate(True)

        def do_DELETE(self):
            self.mutate(False)

        def mutate(self, stored):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.calls.append((self.command, self.path, dict(self.headers), body))
            assert (
                self.path == "/api/runtime/provider-keys"
                and body["model_id"] == state.model
            )
            state.stored = stored
            self.respond(
                state.write_status,
                {
                    **self.metadata(),
                    **({"extra": "must-not-print"} if state.response_fault else {}),
                },
            )

        def metadata(self):
            return {
                "model_id": state.model,
                "status": "added" if state.stored else "missing",
                "cleanup_pending": state.pending,
            }

        def respond(self, status, value):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    state.issuer, state.profile = (
        f"http://127.0.0.1:{http.server_port}",
        tmp_path / "profile",
    )
    with opened(state.profile, create=True) as profile:
        profile.save(Credential(state.issuer, state.actor, state.access, state.refresh))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)


def command(api, monkeypatch, action, *extra):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "keeplane",
            "keys",
            action,
            "--profile",
            str(api.profile),
            "--model",
            api.model,
            *extra,
        ],
    )
    return keeplane.main()


def test_hidden_key_set_status_remove_and_cleanup_metadata(api, monkeypatch, capsys):
    secret = "synthetic-provider-key-12"
    monkeypatch.setattr(provider_keys.getpass, "getpass", lambda _: secret)
    assert command(api, monkeypatch, "set") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "added"
    api.pending = True
    assert command(api, monkeypatch, "status") == 0
    assert json.loads(capsys.readouterr().out)["cleanup_pending"] is True
    assert command(api, monkeypatch, "remove") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "missing"
    assert [row[0] for row in api.calls] == [
        "GET",
        "PUT",
        "GET",
        "GET",
        "GET",
        "DELETE",
    ]
    assert api.calls[1][3] == {"model_id": api.model, "key": secret}
    assert api.calls[-1][3] == {"model_id": api.model}
    for _, path, headers, _ in api.calls:
        assert secret not in path + json.dumps(headers)
        assert (
            headers["Authorization"] == "Bearer " + api.access
            and "Cookie" not in headers
        )
    assert all(secret not in p.read_text() for p in api.profile.iterdir())
    output = capsys.readouterr()
    assert secret not in output.out + output.err


@pytest.mark.parametrize("withdrawal", ["actor", "401", "503"])
@pytest.mark.parametrize("action", ["set", "status", "remove"])
def test_recheck_precedes_prompt_and_key_contact(
    api, monkeypatch, capsys, withdrawal, action
):
    def forbidden(_):
        pytest.fail("A withdrawn account must not be prompted for a key")

    monkeypatch.setattr(provider_keys.getpass, "getpass", forbidden)
    if withdrawal == "actor":
        api.actor = str(uuid.uuid4())
    else:
        api.account_status = int(withdrawal)
    assert command(api, monkeypatch, action) == 1
    assert len(api.calls) == 1 and api.calls[0][1] == "/api/runtime/session"
    output = capsys.readouterr()
    assert (
        api.access not in output.out + output.err
        and api.refresh not in output.out + output.err
    )


@pytest.mark.parametrize("action", ["set", "remove"])
@pytest.mark.parametrize("fault", ["503", "response"])
def test_ambiguous_write_is_not_retried_and_status_reconciles(
    api, monkeypatch, capsys, action, fault
):
    monkeypatch.setattr(
        provider_keys.getpass, "getpass", lambda _: "synthetic-provider-key-12"
    )
    api.write_status, api.response_fault = (
        (503, False) if fault == "503" else (200, True)
    )
    assert command(api, monkeypatch, action) == 1
    assert "may have completed" in capsys.readouterr().err
    assert len(api.calls) == 2
    assert command(api, monkeypatch, "status") == 0
    assert json.loads(capsys.readouterr().out)["status"] == (
        "added" if action == "set" else "missing"
    )
    assert sum(row[0] in {"PUT", "DELETE"} for row in api.calls) == 1


def test_hidden_input_cannot_fall_back_to_echo(api, monkeypatch, capsys):
    def unavailable(_):
        warnings.warn(
            "hidden input unavailable",
            provider_keys.getpass.GetPassWarning,
            stacklevel=1,
        )
        pytest.fail("GetPassWarning must stop before fallback input")

    monkeypatch.setattr(provider_keys.getpass, "getpass", unavailable)
    assert command(api, monkeypatch, "set") == 1
    assert "hidden" in capsys.readouterr().err and len(api.calls) == 1


def test_explicit_pipe_is_bounded_and_private(api, monkeypatch, capsys):
    secret = b"synthetic-provider-key-12"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(secret + b"\r\n")))
    assert command(api, monkeypatch, "set", "--key-stdin") == 0
    assert api.calls[-1][3]["key"] == secret.decode()
    assert secret.decode() not in capsys.readouterr().out
    assert all(secret not in p.read_bytes() for p in api.profile.iterdir())


@pytest.mark.parametrize(
    "raw", [b"x" * 515, b"synthetic\nheader-injection", b"synthetic-key-\xff"]
)
def test_invalid_pipe_never_contacts_key_endpoint(api, monkeypatch, capsys, raw):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    assert command(api, monkeypatch, "set", "--key-stdin") == 1
    assert len(api.calls) == 1
    assert "valid provider key" in capsys.readouterr().err
