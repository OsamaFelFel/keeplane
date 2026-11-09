"""Spec 004 ST11 "A refused key": a task's 401 or 403 on the developer's own key.

Cases: tests/unit/cli-refused-key-cases.md (RK-01 to RK-07). The gateway passes
the provider's answer on, so the CLI spots a 401 or 403 in the runtime's error
events and asks the server to recheck the saved key; `keys list` then shows the
server's verdict.
"""

import json
import subprocess
import uuid

import pytest

from components.cli import coding, opencode_adapter, provider_keys
from components.cli.server_connection import ConnectionError, SignInExpired
from tests.unit.test_cli_project_profile import (  # noqa: F401
    code,
    connected,
    runtime,
)

PROJECT = str(uuid.uuid4())
ISSUER = "https://keeplane.test"
TOKEN = "kpc_" + "a" * 43


def api_error(status, message="Unauthorized"):
    return {
        "type": "error",
        "error": {
            "name": "APIError",
            "data": {"message": message, "statusCode": status, "isRetryable": False},
        },
    }


def lines(*events):
    return "".join(json.dumps(event) + "\n" for event in events)


class Server:
    """The key routes `refused_after_failure` asks, with the answers it is given."""

    def __init__(self, monkeypatch, status="added", verdict="refused", **options):
        self.calls = []
        self.status, self.verdict = status, verdict
        self.own_key = options.get("own_key", True)
        self.listed = options.get("listed", True)
        self.list_error = options.get("list_error")
        self.check_error = options.get("check_error")
        monkeypatch.setattr(provider_keys, "request", self.request)

    def request(self, issuer, path, credential, *, method="GET", payload=None, **_):
        self.calls.append((method, path, payload))
        if path.endswith("/provider-keys"):
            if self.list_error:
                raise self.list_error
            project = path.split("/")[-2]
            rows = [
                {
                    "id": "coder",
                    "own_key_required": self.own_key,
                    "status": self.status if self.own_key else None,
                }
            ]
            return json.dumps(
                {"project_id": project, "models": rows if self.listed else []}
            ).encode()
        if self.check_error:
            raise self.check_error
        return json.dumps(
            {
                "model_id": payload["model_id"],
                "status": self.verdict,
                "cleanup_pending": False,
            }
        ).encode()


# RK-01: spotting the refusal in the runtime's events.
@pytest.mark.parametrize("status", [401, 403])
def test_rk_01_a_401_or_403_error_event_is_a_possible_refusal(status):
    assert coding.provider_refusal(lines({"type": "step_start"}, api_error(status)))


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "Coding finished.\nnot json {\n",
        lines(api_error(400, "Bad request")),
        lines(api_error(429)),
        lines(api_error(503)),
        # A 401 in a part that isn't an error event is not a refusal.
        lines({"type": "text", "part": {"statusCode": 401}}),
        lines({"type": "error", "error": {"statusCode": "401"}}),
        lines({"type": "error", "error": {"statusCode": True}}),
    ],
)
def test_rk_01_other_events_are_not_a_refusal(stdout):
    assert not coding.provider_refusal(stdout)


# RK-02: the recheck only for a saved own key, sending only the model ID.
def test_rk_02_a_saved_own_key_is_rechecked_and_a_refusal_confirmed(monkeypatch):
    server = Server(monkeypatch)
    assert provider_keys.refused_after_failure(ISSUER, TOKEN, PROJECT, "coder")
    assert server.calls == [
        ("GET", f"/api/runtime/projects/{PROJECT}/provider-keys", None),
        ("POST", "/api/runtime/provider-keys/check", {"model_id": "coder"}),
    ]


def test_rk_02_a_key_the_provider_still_accepts_is_not_reported(monkeypatch):
    server = Server(monkeypatch, verdict="added")
    assert not provider_keys.refused_after_failure(ISSUER, TOKEN, PROJECT, "coder")
    assert len(server.calls) == 2


def test_rk_02_a_key_already_refused_needs_no_new_provider_check(monkeypatch):
    server = Server(monkeypatch, status="refused")
    assert provider_keys.refused_after_failure(ISSUER, TOKEN, PROJECT, "coder")
    assert [call[0] for call in server.calls] == ["GET"]


@pytest.mark.parametrize(
    "options",
    [{"status": "missing"}, {"own_key": False}, {"listed": False}],
    ids=["no-saved-key", "shared-or-no-key", "not-allowed"],
)
def test_rk_03_no_saved_own_key_means_no_check(monkeypatch, options):
    server = Server(monkeypatch, **options)
    assert not provider_keys.refused_after_failure(ISSUER, TOKEN, PROJECT, "coder")
    assert [call[0] for call in server.calls] == ["GET"]


@pytest.mark.parametrize(
    "options",
    [
        {"list_error": SignInExpired()},
        {"list_error": ConnectionError("Older server", 404)},
        {"list_error": ConnectionError("Down", 503)},
        {"check_error": SignInExpired()},
        {"check_error": ConnectionError("Provider unavailable", 503)},
        {"verdict": "unknown"},
    ],
    ids=["list-401", "older-server", "list-503", "check-401", "check-503", "invalid"],
)
def test_rk_04_a_server_that_cant_confirm_leaves_the_tasks_error(monkeypatch, options):
    Server(monkeypatch, **options)
    assert not provider_keys.refused_after_failure(ISSUER, TOKEN, PROJECT, "coder")


def test_rk_04_an_invalid_key_list_is_not_trusted(monkeypatch):
    monkeypatch.setattr(
        provider_keys,
        "request",
        lambda *a, **k: b'{"project_id": "other", "models": []}',
    )
    assert not provider_keys.refused_after_failure(ISSUER, TOKEN, PROJECT, "coder")


# RK-05 to RK-07: `keeplane code` end to end with the runtime faked.
def failed_turn(monkeypatch, fake, *events, returncode=0):
    def turn(command, **options):
        fake[1].append((command, options))
        return subprocess.CompletedProcess(command, returncode, lines(*events), "")

    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)


REFUSED = (
    "The provider refused your own key for coder, so this task stopped. "
    "Replace it with `keeplane keys set --model coder`. "
    "Run `keeplane keys list` to see your keys.\n"
)


@pytest.mark.parametrize("status", [401, 403])
def test_rk_05_code_tells_the_developer_to_replace_a_refused_key(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    status,
):
    server = Server(monkeypatch)
    failed_turn(
        monkeypatch,
        runtime,
        {"type": "step_start"},
        api_error(status, "Incorrect API key provided"),
    )
    assert code(monkeypatch, connected, runtime, PROJECT, tmp_path) == 1
    output = capsys.readouterr()
    # Not an expired sign-in, not a model outage: the key, and how to fix it.
    assert output.err == REFUSED
    assert json.loads(output.out.splitlines()[-1])["type"] == "error"
    assert [call[1] for call in server.calls] == [
        f"/api/runtime/projects/{PROJECT}/provider-keys",
        "/api/runtime/provider-keys/check",
    ]
    assert len(runtime[1]) == 1
    assert all("/model-alternatives" not in row[1] for row in connected.calls)
    assert connected.access not in output.out + output.err


def test_rk_06_a_401_the_server_doesnt_confirm_is_still_an_expired_sign_in(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
):
    Server(monkeypatch, list_error=SignInExpired())
    failed_turn(monkeypatch, runtime, api_error(401))
    assert code(monkeypatch, connected, runtime, PROJECT, tmp_path) == 1
    assert capsys.readouterr().err == (
        "Your Keeplane sign-in has expired, so nothing was sent. "
        "Run `keeplane login` to sign in again.\n"
    )


def test_rk_06_a_403_on_a_key_that_still_works_says_nothing_about_the_key(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
):
    Server(monkeypatch, verdict="added")
    failed_turn(monkeypatch, runtime, api_error(403, "Forbidden"))
    assert code(monkeypatch, connected, runtime, PROJECT, tmp_path) == 1
    assert "key" not in capsys.readouterr().err


def test_rk_07_a_task_that_succeeds_or_fails_otherwise_asks_nothing(
    connected,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
):
    server = Server(monkeypatch)
    assert code(monkeypatch, connected, runtime, PROJECT, tmp_path) == 0
    failed_turn(monkeypatch, runtime, api_error(503, "Service Unavailable"))
    assert code(monkeypatch, connected, runtime, PROJECT, tmp_path) == 1
    assert not server.calls
    assert "coder is unavailable right now" in capsys.readouterr().err
