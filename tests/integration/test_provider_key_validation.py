"""Real bounded HTTP against synthetic providers; never paid cloud requests."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
from threading import Thread
import time

import pytest
from django.db import transaction

from model_registry.fingerprints import fingerprint
from model_registry.key_validation import DjangoProviderKeyValidator, ProviderKeyRefused
from model_registry.models import ModelApproval

pytestmark = pytest.mark.django_db(transaction=True)
KEY = "synthetic-provider-validation-key"


@pytest.fixture
def provider():
    state = {"mode": "accepted", "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append(
                {
                    "path": self.path,
                    "body": body,
                    "key_matches": self.headers.get("Authorization") == "Bearer " + KEY
                    or self.headers.get("x-api-key") == KEY,
                    "anthropic_version": self.headers.get("anthropic-version"),
                }
            )
            mode = state["mode"]
            if mode == "stall":
                time.sleep(1)
            status = (
                mode if isinstance(mode, int) else 302 if mode == "redirect" else 200
            )
            self.send_response(status)
            if mode == "redirect":
                self.send_header("Location", state["url"] + "/trap")
            self.end_headers()
            answer = {
                "type": "message",
                "content": [],
                "choices": [{"message": {"content": ""}}],
            }
            raw = (
                b"x" * 65537
                if mode == "large"
                else b"invalid"
                if mode == "invalid"
                else json.dumps({} if mode == "empty" else answer).encode()
            )
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/v1"
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


class Gateway:
    def __init__(self, resource):
        self.resource, self.reads = resource, 0
        self.before_read = lambda: None

    def request(self, path, *, timeout, connection_retries):
        assert (path, timeout, connection_retries) == (
            "/api/config/resources/llm.model",
            5,
            0,
        )
        self.reads += 1
        self.before_read()
        return 200, {"resources": [deepcopy(self.resource)]}


def setup(provider, kind="openAI", timeout=2):
    resource = {
        "id": "model",
        "revision": 1,
        "value": {
            "name": "model",
            "provider": kind,
            "params": {"model": "upstream-model", "baseUrl": provider["url"]},
        },
    }
    ModelApproval.objects.create(
        model_id="model",
        key_choice="personal",
        gateway_fingerprint=fingerprint("model", [resource]),
    )
    gateway = Gateway(resource)
    return DjangoProviderKeyValidator(
        gateway, timeout=timeout, allow_loopback_http=True
    ), gateway


@pytest.mark.parametrize("explicit_id", [False, True])
@pytest.mark.parametrize(
    "kind,path,limit",
    [
        ("openAI", "/v1/chat/completions", "max_completion_tokens"),
        ("anthropic", "/v1/messages", "max_tokens"),
    ],
)
def test_fixed_provider_request_issues_definition_bound_verification(
    provider, kind, path, limit, explicit_id
):
    validator, gateway = setup(provider, kind)
    if explicit_id:
        gateway.resource["value"]["id"] = "model"
        ModelApproval.objects.update(
            gateway_fingerprint=fingerprint("model", [gateway.resource])
        )
    verified = validator("actor", "model", KEY)
    assert (verified.owner_id, verified.model_id) == ("actor", "model")
    assert verified.definition_fingerprint == fingerprint("model", [gateway.resource])
    assert gateway.reads == 2 and len(provider["calls"]) == 1
    call = provider["calls"][0]
    assert call["path"] == path and call["key_matches"]
    assert call["body"] == {
        "model": "upstream-model",
        "messages": [{"role": "user", "content": "Reply OK."}],
        "stream": False,
        limit: 1,
    }
    assert call["anthropic_version"] == ("2023-06-01" if kind == "anthropic" else None)


@pytest.mark.parametrize(
    "native_id", ["other", "", None, 1, ["model"], {"id": "model"}]
)
def test_invalid_native_id_is_refused_before_provider_contact(provider, native_id):
    validator, gateway = setup(provider)
    original = fingerprint("model", [gateway.resource])
    gateway.resource["value"]["id"] = native_id
    current = fingerprint("model", [gateway.resource])
    assert current != original
    # A current approval cannot make a mismatched/malformed ID acceptable.
    ModelApproval.objects.update(gateway_fingerprint=current)
    with pytest.raises(ValueError, match="unsupported"):
        validator("actor", "model", KEY)
    assert not provider["calls"]


def test_adding_matching_native_id_requires_fresh_approval(provider):
    validator, gateway = setup(provider)
    gateway.resource["value"]["id"] = "model"
    with pytest.raises(ValueError, match="changed"):
        validator("actor", "model", KEY)
    assert not provider["calls"]
    ModelApproval.objects.update(
        gateway_fingerprint=fingerprint("model", [gateway.resource])
    )
    verified = validator("actor", "model", KEY)
    assert verified.definition_fingerprint == fingerprint("model", [gateway.resource])
    assert len(provider["calls"]) == 1


@pytest.mark.parametrize(
    "mode,error",
    [
        (401, ProviderKeyRefused),
        (403, ProviderKeyRefused),
        (429, ValueError),
        (500, ValueError),
        ("redirect", ValueError),
        ("invalid", ValueError),
        ("empty", ValueError),
        ("large", ValueError),
    ],
)
def test_refusal_and_unverifiable_responses_never_issue_verification(
    provider, mode, error
):
    validator, _ = setup(provider)
    provider["mode"] = mode
    with pytest.raises(error) as result:
        validator("actor", "model", KEY)
    assert KEY not in str(result.value) and len(provider["calls"]) == 1


def test_wall_deadline_kills_and_reaps_owned_worker(provider, monkeypatch):
    validator, _ = setup(provider, timeout=0.15)
    provider["mode"] = "stall"
    processes, original = [], subprocess.Popen

    def launch(args, **kwargs):
        assert KEY not in json.dumps(args)
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        process = original(args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("model_registry.key_validation.subprocess.Popen", launch)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        validator("actor", "model", KEY)
    assert time.monotonic() - started < 1.5
    assert processes[0].stdin.closed and processes[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


@pytest.mark.parametrize("change", ["unapproved", "revision", "unsupported", "http"])
def test_unapproved_changed_or_unsupported_definition_never_contacts_provider(
    provider, change
):
    validator, gateway = setup(provider)
    if change == "unapproved":
        ModelApproval.objects.all().delete()
    elif change == "revision":
        gateway.resource["revision"] += 1
    elif change == "unsupported":
        gateway.resource["value"]["params"]["headers"] = {"secret": KEY}
        ModelApproval.objects.update(
            gateway_fingerprint=fingerprint("model", [gateway.resource])
        )
    else:
        validator.allow_loopback_http = False
    with pytest.raises(ValueError):
        validator("actor", "model", KEY)
    assert provider["calls"] == []


def test_definition_change_during_validation_or_before_commit_is_refused(provider):
    validator, gateway = setup(provider)

    def changed():
        if gateway.reads == 2:
            gateway.resource["revision"] += 1

    gateway.before_read = changed
    with pytest.raises(ValueError, match="changed"):
        validator("actor", "model", KEY)
    assert len(provider["calls"]) == 1
    gateway.resource["revision"] = 1
    gateway.before_read = lambda: None
    verified = validator("actor", "model", KEY)
    with transaction.atomic():
        validator.require_current(verified)
    gateway.resource["revision"] = 2
    with transaction.atomic(), pytest.raises(ValueError, match="changed"):
        validator.require_current(verified)
