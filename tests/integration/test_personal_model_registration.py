"""Personal setup probes the provider without borrowing a developer's key."""

import json
import ssl
import subprocess
import time
from copy import deepcopy
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from common.errors import StorageUnavailable
from django.test import Client
from model_registry import registration
from model_registry.fingerprints import fingerprint
from model_registry.models import ModelApproval
from model_registry.provider_probe import probe_request, provider_answers
from model_registry.registration import ModelManagement

from tests.unit.test_model_registration_ids import Gateway


@pytest.fixture
def provider(request, tmp_path):
    state = {
        "status": 401,
        "calls": [],
        "body": b"{}",
        "delay": 0,
        "after": lambda: None,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            state["calls"].append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    ),
                }
            )
            state["after"]()
            time.sleep(state["delay"])
            self.send_response(state["status"])
            self.send_header("Location", state["url"] + "/trap")
            self.end_headers()
            try:
                self.wfile.write(state["body"])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = getattr(request, "param", False)
    if tls:
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=Keeplane disposable provider",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        key.chmod(0o600)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        state["ca"] = str(cert)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    scheme = "https" if tls else "http"
    state["url"] = f"{scheme}://127.0.0.1:{server.server_port}/v1"
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def definition(provider, kind="openAI"):
    return {
        "id": "personal",
        "name": "personal",
        "provider": kind,
        "params": {"model": "upstream", "baseUrl": provider["url"]},
    }


@pytest.mark.parametrize(
    "kind,path,limit",
    [
        ("openAI", "/v1/chat/completions", "max_completion_tokens"),
        ("anthropic", "/v1/messages", "max_tokens"),
    ],
)
@pytest.mark.parametrize("status", [200, 401, 403])
def test_real_probe_sends_only_fixed_metadata_and_no_credentials(
    provider, kind, path, limit, status, monkeypatch
):
    provider["status"] = status
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    assert provider_answers(definition(provider, kind), allow_loopback_http=True)
    assert len(provider["calls"]) == 1
    call = provider["calls"][0]
    assert call["path"] == path
    assert call["body"] == {
        "model": "upstream",
        "messages": [{"role": "user", "content": "Reply OK."}],
        "stream": False,
        limit: 1,
    }
    headers = {key.lower(): value for key, value in call["headers"].items()}
    assert not (
        {"authorization", "x-api-key", "cookie", "x-keeplane-gateway-credential"}
        & headers.keys()
    )
    assert headers.get("anthropic-version") == (
        "2023-06-01" if kind == "anthropic" else None
    )


@pytest.mark.parametrize("status", [302, 400, 404, 429, 500])
def test_unavailable_or_redirected_provider_is_not_approved(provider, status):
    provider["status"] = status
    assert not provider_answers(definition(provider), allow_loopback_http=True)
    assert len(provider["calls"]) == 1


@pytest.mark.parametrize(
    "body", [b"not-json", b"[]", b"x" * 65537], ids=["invalid", "array", "oversized"]
)
def test_success_response_is_bounded_and_must_be_json(provider, body):
    provider.update(status=200, body=body)
    assert not provider_answers(definition(provider), allow_loopback_http=True)


def test_wall_deadline_reaps_owned_worker(provider, monkeypatch):
    processes = []
    original = registration.provider_answers.__globals__["subprocess"].Popen

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("model_registry.provider_probe.subprocess.Popen", spawn)
    provider["delay"] = 1
    started = time.monotonic()
    assert not provider_answers(
        definition(provider), timeout=0.2, allow_loopback_http=True
    )
    assert time.monotonic() - started < 0.8
    assert len(processes) == 1 and processes[0].poll() is not None


@pytest.mark.parametrize(
    "base",
    [
        "http://provider.invalid/v1",
        "https://user:password@provider.invalid/v1",
        "https://provider.invalid/v1?token=value",
        "https://provider.invalid/v1#fragment",
        "https://provider.invalid:bad/v1",
        "https://provider.invalid/\n",
    ],
)
def test_invalid_target_has_zero_provider_contacts(provider, base):
    resource = definition(provider)
    resource["params"]["baseUrl"] = base
    assert not provider_answers(resource)
    assert not provider["calls"]


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "custom"},
        {"id": "different"},
        {"auth": {"key": {"value": "secret"}}},
        {"params": {"model": "upstream", "unknown": True}},
        {"unknown": True},
        {"auth": False},
        {"auth": 0},
        {"auth": ""},
        {"auth": []},
    ],
)
def test_unsupported_definition_is_never_probed(provider, change):
    resource = definition(provider)
    resource.update(change)
    assert not provider_answers(resource, allow_loopback_http=True)
    assert not provider["calls"]


def test_production_requires_https_even_for_loopback(provider):
    assert not provider_answers(definition(provider))
    assert not provider["calls"]
    request = probe_request(
        {"name": "personal", "provider": "openAI", "params": {"model": "upstream"}}
    )
    assert request["url"] == "https://api.openai.com/v1/chat/completions"


@pytest.mark.parametrize("provider", [True], indirect=True)
def test_production_https_probe_requires_the_actual_certificate_authority(
    provider, monkeypatch
):
    monkeypatch.setenv("SSL_CERT_FILE", provider["ca"])
    assert provider_answers(definition(provider))
    assert len(provider["calls"]) == 1
    monkeypatch.delenv("SSL_CERT_FILE")
    assert not provider_answers(definition(provider))
    assert len(provider["calls"]) == 1


@pytest.fixture
def registrar(domain_services, provider, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Personal setup must never read or save any provider key")

    monkeypatch.setattr(registration, "save_provider_key", forbidden)
    monkeypatch.setattr(registration, "remove_provider_key", forbidden)
    gateway = Gateway()
    original_request = gateway.request

    def request(path, *args, **kwargs):
        assert path != "/v1/chat/completions", (
            "Operator credentials cannot establish Personal provider reachability"
        )
        return original_request(path, *args, **kwargs)

    gateway.request = request
    result = ModelManagement(
        domain_services.catalog,
        domain_services.classes,
        gateway,
        None,
        "managed",
        None,
        str(tmp_path / "keys"),
        set(),
        {"openai": provider["url"], "anthropic": provider["url"]},
        "",
        provider_probe=partial(provider_answers, allow_loopback_http=True),
    )
    return result


def add(registrar, source="openai", **kwargs):
    return registrar.add(
        {
            "name": "personal",
            "model": "upstream",
            "source": source,
            "key_choice": "personal",
            **kwargs,
        }
    )


@pytest.mark.parametrize("source", ["openai", "anthropic"])
def test_personal_add_creates_real_definition_bound_approval_without_a_key(
    registrar, provider, source
):
    assert add(registrar, source)[0] == 200
    entry = registrar.gateway.records["personal"]
    approval = ModelApproval.objects.get(pk="personal")
    assert entry["value"]["id"] == "personal" and "auth" not in entry["value"]
    assert approval.key_choice == "personal" and approval.owned_by_keeplane
    assert approval.gateway_fingerprint == fingerprint("personal", [entry])
    assert len(provider["calls"]) == 1


def test_failed_provider_probe_removes_only_its_new_definition(registrar, provider):
    registrar.gateway.records["unrelated"] = {
        "id": "unrelated",
        "revision": 2,
        "value": {"name": "unrelated"},
    }
    original = deepcopy(registrar.gateway.records)
    provider["status"] = 500
    status, body = add(registrar)
    assert status == 503 and "Nothing was saved" in body["error"]
    assert registrar.gateway.records == original and not ModelApproval.objects.exists()


def test_changed_definition_during_probe_is_preserved_without_approval(
    registrar, provider
):
    def change():
        registrar.gateway.records["personal"]["value"]["params"]["model"] = "changed"
        registrar.gateway.records["personal"]["revision"] += 1

    provider["after"] = change
    status, body = add(registrar)
    assert status == 503 and "may remain" in body["error"]
    assert (
        registrar.gateway.records["personal"]["value"]["params"]["model"] == "changed"
    )
    assert not ModelApproval.objects.exists()


def test_approval_storage_failure_rolls_back_matching_definition(
    registrar, monkeypatch
):
    def fail(*args, **kwargs):
        raise StorageUnavailable()

    monkeypatch.setattr(registrar.catalog, "approve", fail)
    assert add(registrar)[0] == 503
    assert not registrar.gateway.records and not ModelApproval.objects.exists()


@pytest.mark.parametrize("field", ["shared_key", "replace_shared_key"])
def test_personal_add_rejects_submitted_organization_key(registrar, provider, field):
    assert add(registrar, **{field: "synthetic-shared-provider-key"})[0] == 400
    assert not provider["calls"] and not registrar.gateway.records


def test_personal_edit_rechecks_provider_and_preserves_ownership(registrar, provider):
    assert add(registrar)[0] == 200
    assert registrar.setup("personal", {"key_choice": "personal"})[0] == 200
    approval = ModelApproval.objects.get(pk="personal")
    assert approval.key_choice == "personal" and approval.owned_by_keeplane
    assert len(provider["calls"]) == 2
    old = approval.gateway_fingerprint
    provider["status"] = 500
    assert registrar.setup("personal", {"key_choice": "personal"})[0] == 503
    approval.refresh_from_db()
    assert approval.gateway_fingerprint == old


@pytest.mark.parametrize("provider", [True], indirect=True)
@pytest.mark.parametrize(
    "role,status", [("anonymous", 401), ("developer", 403), ("admin", 200)]
)
def test_actual_admin_api_keeps_roles_csrf_and_classes(
    provider, registrar, domain_services, monkeypatch, role, status
):
    from model_registry import use_cases

    identity = domain_services.identity
    admin_token = identity.login("first-admin", "first-test-password-123")
    token = None
    if role == "developer":
        identity.create_user(
            {
                "username": "personal-developer",
                "password": "synthetic-account-password",
                "role": "developer",
            }
        )
        token = identity.login("personal-developer", "synthetic-account-password")
    elif role == "admin":
        token = admin_token
    monkeypatch.setattr("common.api.IDENTITY", identity)
    monkeypatch.setattr(use_cases, "CATALOG", domain_services.catalog)
    monkeypatch.setattr(use_cases, "DATA_CLASSES", domain_services.classes)
    monkeypatch.setattr(use_cases, "MODEL_GATEWAY", registrar.gateway)
    monkeypatch.setenv("PREVIEW_OPENAI_BASE_URL", provider["url"])
    monkeypatch.setenv("SSL_CERT_FILE", provider["ca"])
    domain_services.classes.set_enabled(True)
    client = Client(enforce_csrf_checks=True)
    if token:
        client.cookies["keeplane_session"] = token
    csrf = client.get("/api/auth-options").json()["csrf_token"]
    body = json.dumps(
        {
            "name": "personal",
            "model": "upstream",
            "source": "openai",
            "key_choice": "personal",
            "approved_classes": ["Public"],
        }
    )
    assert (
        client.post(
            "/api/models",
            body,
            content_type="application/json",
            HTTP_X_KEEPLANE_ACTION="1",
        ).status_code
        == 403
    )
    assert client.post(
        "/api/models", body, content_type="application/json", HTTP_X_CSRFTOKEN=csrf
    ).status_code == (403 if role != "anonymous" else 401)
    assert not provider["calls"] and not ModelApproval.objects.exists()
    response = client.post(
        "/api/models",
        body,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_X_KEEPLANE_ACTION="1",
    )
    assert response.status_code == status
    if role == "admin":
        assert ModelApproval.objects.get(pk="personal").approved_classes == ["Public"]
        assert len(provider["calls"]) == 1
    else:
        assert not provider["calls"] and not ModelApproval.objects.exists()
