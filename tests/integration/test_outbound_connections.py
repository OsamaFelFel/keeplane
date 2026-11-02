"""At runtime the server connects only where it is configured to (ADR 009).

Cases EGR-10 to EGR-14 in tests/unit/outbound-connection-cases.md. Each check
runs under a socket guard (tests/support/outbound.py) that refuses every
connection and name lookup except the loopback test endpoints the check
declares, so any extra destination, such as telemetry, an update check or a
download, fails the check before anything leaves the machine.
"""

import json
import secrets
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import Client

from tests.support.outbound import OutboundGuard, OutboundRefused

ADMIN_PASSWORD = "first-test-password-123"


class Endpoint:
    """A loopback HTTP server answering JSON by path; records every request."""

    def __init__(self, routes, *, status=200):
        self.routes, self.status, self.calls = routes, status, []
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                endpoint.calls.append(
                    (self.command, self.path, dict(self.headers), body)
                )
                route = endpoint.routes.get(self.path.split("?", 1)[0])
                value = route(self.command, body) if callable(route) else route
                status, value = (
                    (404, {"error": "not found"})
                    if value is None
                    else (endpoint.status, value)
                )
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_DELETE = answer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def paths(self):
        return [path for _, path, _, _ in self.calls]


def fake_gateway():
    resources = []

    def resource_list(method, body):
        if method in ("POST", "PUT"):
            for row in json.loads(body).get("resources", []):
                value = row["value"]
                resources[:] = [r for r in resources if r["id"] != value["name"]]
                resources.append({"id": value["name"], "value": value, "revision": 1})
            return {}
        return {"resources": resources}

    return Endpoint(
        {
            "/v1/models": lambda m, b: {"data": [{"id": r["id"]} for r in resources]},
            "/api/config/resources/llm.model": resource_list,
            "/api/runtime": {"build": {"version": "test"}},
            "/v1/chat/completions": {
                "choices": [{"message": {"role": "assistant", "content": "OK"}}]
            },
        }
    )


def fake_runner():
    return Endpoint(
        {
            "/v1/models": {"data": [{"id": "runner-model"}]},
            "/props": {"default_generation_settings": {"n_ctx": 4096}},
            "/v1/chat/completions": {
                "choices": [{"message": {"role": "assistant", "content": "OK"}}]
            },
        }
    )


# EGR-10 The guard refuses what it must: a connection to any address that is
# not a declared loopback endpoint and a lookup of any outside name, before a
# packet is sent; loopback endpoints it was given still work.
def test_egr_10_the_guard_refuses_undeclared_destinations():
    import socket
    from urllib.error import URLError
    from urllib.request import urlopen

    with Endpoint({"/": {"ok": True}}) as endpoint:
        guard = OutboundGuard({endpoint.port})
        with guard.active():
            with urlopen(endpoint.url + "/", timeout=5) as response:
                assert json.load(response) == {"ok": True}
            with pytest.raises(OutboundRefused):
                socket.create_connection(("192.0.2.1", 443), timeout=1)
            with pytest.raises(OutboundRefused):
                socket.create_connection(("127.0.0.1", 9), timeout=1)
            with pytest.raises(URLError):
                urlopen("https://telemetry.example.invalid/ping", timeout=1)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                with pytest.raises(OutboundRefused):
                    udp.sendto(b"ping", ("192.0.2.2", 53))
                with pytest.raises(OutboundRefused):
                    udp.sendto(b"ping", 0, ("192.0.2.3", 514))
                with pytest.raises(OutboundRefused):
                    udp.sendmsg([b"ping"], [], 0, ("192.0.2.4", 123))
            with pytest.raises(socket.herror):
                socket.gethostbyaddr("192.0.2.5")
            with pytest.raises(socket.herror):
                socket.getnameinfo(("192.0.2.6", 80), 0)
            with pytest.raises(socket.gaierror):
                socket.gethostbyname("updates.example.invalid")
        assert guard.refused == [
            ("192.0.2.1", 443),
            ("127.0.0.1", 9),
            ("telemetry.example.invalid", 443),
            ("192.0.2.2", 53),
            ("192.0.2.3", 514),
            ("192.0.2.4", 123),
            ("192.0.2.5", None),
            ("192.0.2.6", None),
            ("updates.example.invalid", None),
        ]
    # The guard is removed afterwards.
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        assert getattr(socket.socket, name).__name__ == name
    for name in ("getaddrinfo", "gethostbyaddr", "getnameinfo"):
        assert getattr(socket, name).__name__ == name


@pytest.fixture
def admin(domain_services, monkeypatch):
    from common.api import MODEL_GATEWAY

    with fake_gateway() as gateway, fake_runner() as runner:
        guard = OutboundGuard({gateway.port, runner.port})
        monkeypatch.setattr(MODEL_GATEWAY, "base_url", gateway.url)
        monkeypatch.setattr(MODEL_GATEWAY, "runtime_key_file", "")
        monkeypatch.setattr(MODEL_GATEWAY, "admin_key_file", "")
        services = domain_services
        client = Client()
        with (
            patch("common.api.IDENTITY", services.identity),
            patch("model_registry.views.CATALOG", services.catalog),
            patch("model_registry.use_cases.CATALOG", services.catalog),
            patch("model_registry.use_cases.DATA_CLASSES", services.classes),
            patch("model_registry.views.RUNNER_URLS", {runner.url}),
            patch("model_registry.use_cases.RUNNER_URLS", {runner.url}),
            patch("projects.views.AUDIT", services.audit),
            patch("audit.views.AUDIT", services.audit),
            patch("data_classes.views.DATA_CLASSES", services.classes),
        ):
            client.cookies["keeplane_session"] = services.identity.login(
                "first-admin", ADMIN_PASSWORD
            )

            def call(method, path, body=None):
                kwargs = {"HTTP_X_KEEPLANE_ACTION": "1"}
                if method != "get":
                    kwargs["content_type"] = "application/json"
                    kwargs["data"] = json.dumps(body or {})
                return getattr(client, method)(path, **kwargs)

            yield SimpleNamespace(
                call=call, guard=guard, gateway=gateway, runner=runner
            )


# EGR-11 An admin journey through the running app (identity, models, runner
# discovery, adding a runner model, gateway status and health, readiness,
# data classes, projects and Audit) connects only to the configured gateway
# and runner, with no other connection or name lookup.
def test_egr_11_an_admin_journey_reaches_only_the_gateway_and_runner(admin):
    call, guard = admin.call, admin.guard
    with guard.active():
        assert call("get", "/api/identity").status_code == 200
        assert call("get", "/api/models").status_code == 200
        found = call("post", "/api/runners/models", {"address": admin.runner.url})
        assert found.status_code == 200 and found.json()["models"] == ["runner-model"]
        added = call(
            "post",
            "/api/models",
            {
                "name": "runner-model",
                "model": "runner-model",
                "source": "runner",
                "address": admin.runner.url,
            },
        )
        assert added.status_code < 500, added.content
        assert call("get", "/api/models").status_code == 200
        assert call("get", "/api/status").status_code == 200
        assert call("get", "/health").status_code == 200
        assert call("get", "/health/app").status_code == 200
        assert call("get", "/health/ready").status_code in (200, 503)
        assert call("get", "/api/data-classes").status_code == 200
        assert call("get", "/api/projects").status_code == 200
        assert call("get", "/api/audit/options").status_code == 200
    assert guard.refused == []
    assert {port for _, port in guard.attempts} == {
        admin.gateway.port,
        admin.runner.port,
    }
    assert "/v1/models" in admin.gateway.paths()
    assert "/api/runtime" in admin.gateway.paths()
    assert "/v1/models" in admin.runner.paths()


def write_key(tmp_path):
    key = tmp_path / "runtime-key"
    key.write_text(secrets.token_urlsafe(32))
    return key


# EGR-12 Each runtime call site reaches only the address it is given: the
# gateway adapter, every listed gateway copy, a copy's applied configuration,
# a runner, the customer-run gateway preflight, the certificate check and the
# enroller's loopback admin read. Nothing else is contacted.
def test_egr_12_each_call_site_reaches_only_its_configured_address(
    tmp_path, monkeypatch
):
    from common import certificates
    from integrations.gateway import preflight
    from integrations.gateway.adapter import AgentgatewayModelAdapter
    from integrations.gateway.applied import AppliedStateUnavailable, read_applied
    from integrations.gateway.copies import GatewayCopies
    from integrations.runners import local_runner
    from model_registry.runtime_installation import (
        RuntimeInstallationUnavailable,
        local_applied,
    )

    key = write_key(tmp_path)
    with fake_gateway() as gateway, fake_gateway() as copy, fake_runner() as runner:
        guard = OutboundGuard({gateway.port, copy.port, runner.port, 15000})
        with guard.active():
            adapter = AgentgatewayModelAdapter(gateway.url, str(key), str(key))
            assert adapter.models()[0] == 200
            assert adapter.resources()[0] == 200
            copies = GatewayCopies.from_environment(
                adapter, {"GATEWAY_COPY_URLS": copy.url}
            )
            copies.confirm("absent-model", None)
            with pytest.raises(AppliedStateUnavailable):
                read_applied(
                    SimpleNamespace(base_url=gateway.url, runtime_key_file=str(key))
                )
            assert local_runner(runner.url, {runner.url})[0] == 200
            monkeypatch.setattr(preflight, "URL", gateway.url)
            monkeypatch.setattr(preflight, "ADMIN_KEY_FILE", str(key))
            assert preflight.fetch("/api/runtime")[0] == 200
            row = certificates.server_certificate(
                "127.0.0.1",
                gateway.port,
                certificates.ssl.create_default_context(),
                certificates.datetime.now(certificates.timezone.utc),
                30,
                timeout=2,
            )
            assert row["address"] == f"127.0.0.1:{gateway.port}"
            # Nothing listens on 15000 here; only the attempt matters.
            with suppress(RuntimeInstallationUnavailable, OSError):
                local_applied()
        assert guard.refused == []
        assert set(guard.attempts) <= {
            ("127.0.0.1", gateway.port),
            ("127.0.0.1", copy.port),
            ("127.0.0.1", runner.port),
            ("127.0.0.1", 15000),
        }
        assert ("127.0.0.1", 15000) in guard.attempts
        assert copy.paths() and set(copy.paths()) == {"/api/config/resources/llm.model"}
        assert "/internal/keeplane/applied" in gateway.paths()


# EGR-13 Proxies: the applied-configuration read, the provider-key check (its
# worker started by the key validator) and the Personal provider probe never
# use a proxy from the environment; the gateway adapter and runner discovery
# use one when the process starts with one set.
PROXIED = """
import sys
sys.path.insert(0, sys.argv[1])
from integrations.gateway.adapter import AgentgatewayModelAdapter
from integrations.runners import local_runner
AgentgatewayModelAdapter(sys.argv[2], "", "").models()
local_runner(sys.argv[3], {sys.argv[3]})
"""


def test_egr_13_which_calls_use_an_environment_proxy(tmp_path, monkeypatch):
    import subprocess
    import sys

    from integrations.gateway.applied import AppliedStateUnavailable, read_applied
    from model_registry.key_validation import (
        DjangoProviderKeyValidator,
        ProviderKeyRefused,
    )
    from model_registry.provider_probe import provider_answers

    from tests.support.outbound import SERVER

    key = write_key(tmp_path)
    with (
        Endpoint({}) as proxy,
        fake_gateway() as gateway,
        fake_runner() as runner,
        Endpoint({"/v1/chat/completions": {}}, status=401) as provider,
    ):
        for name in ("http_proxy", "HTTP_PROXY"):
            monkeypatch.setenv(name, proxy.url)
        for name in ("no_proxy", "NO_PROXY"):
            monkeypatch.setenv(name, "")
        with pytest.raises(AppliedStateUnavailable):
            read_applied(
                SimpleNamespace(base_url=gateway.url, runtime_key_file=str(key))
            )
        assert "/internal/keeplane/applied" in gateway.paths()
        definition = {
            "name": "personal",
            "provider": "openAI",
            "params": {"model": "upstream", "baseUrl": provider.url + "/v1"},
        }
        assert provider_answers(definition, allow_loopback_http=True)
        assert provider.paths() == ["/v1/chat/completions"]
        # The real key check, with the approved definition read stubbed: the
        # validator starts its worker, which sends the key to the provider.
        validator = DjangoProviderKeyValidator(None)
        approved = {
            "provider": "openAI",
            "model": "upstream",
            "url": provider.url + "/v1/chat/completions",
        }
        monkeypatch.setattr(
            validator, "_definition", lambda model_id, lock=False: ("fp", approved)
        )
        with pytest.raises(ProviderKeyRefused):
            validator("owner", "personal", "synthetic-developer-key-1234")
        assert provider.paths() == ["/v1/chat/completions"] * 2
        sent = {k.lower(): v for k, v in provider.calls[1][2].items()}
        assert sent["authorization"] == "Bearer synthetic-developer-key-1234"
        assert proxy.calls == []
        subprocess.run(
            [sys.executable, "-c", PROXIED, str(SERVER), gateway.url, runner.url],
            check=True,
            timeout=60,
        )
        assert sorted(proxy.paths()) == sorted(
            [gateway.url + "/v1/models", runner.url + "/v1/models"]
        )


# EGR-14 With the optional detector installed, loading spaCy and Presidio and
# checking requests opens no connection and looks up no name.
@pytest.mark.optional
def test_egr_14_the_detector_loads_and_checks_without_the_network():
    pytest.importorskip("presidio_analyzer")
    spacy = pytest.importorskip("spacy")
    if not spacy.util.is_package("en_core_web_lg"):
        pytest.skip("The en_core_web_lg model is not installed")
    from personal_data.engine import PresidioDetector

    guard = OutboundGuard()
    with guard.active():
        detector = PresidioDetector("en_core_web_lg")
        found = detector.find("Mail amara.okonkwo@example.com about the build")
    assert any(row["type"] == "EMAIL" for row in found)
    assert guard.attempts == [] and guard.refused == []
