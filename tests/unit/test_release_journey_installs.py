"""The disposable release installs follow the guides they check (task 009-15).

Cases: release-journey-install-cases.md (RJI-01 to RJI-05). The installs
themselves run in the release-journey job; these checks read what they would
start, with no Docker.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tests.fixtures import release_journey
from tests.fixtures.release_journey import (
    COPIES,
    CUSTOMER_MODEL,
    FORWARD_NEVER,
    ReleaseInstall,
    customer_gateway,
    front_server,
)

KEY_ONLY = "/internal/runtime/authorize/runtime-key"
FINAL = "/internal/runtime/authorize/selected"


@pytest.fixture
def written(tmp_path, monkeypatch):
    """Write an install's files with no Docker and no openssl."""
    monkeypatch.setenv("KEEPLANE_RELEASE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(
        ReleaseInstall, "command", lambda self, *args, **kwargs: "sha256:" + "0" * 64
    )

    class Up:
        @staticmethod
        def preview_tls(directory, days):
            directory.mkdir()
            for name in ("ca.pem", "provider.pem", "provider.key"):
                (directory / name).write_text("synthetic")

    monkeypatch.setattr(release_journey, "load", lambda name, path: Up)
    made = []

    def make(mode):
        install = ReleaseInstall(mode, "keeplane-preview:postgres-cli-auth-local")
        made.append(install)
        compose = json.loads(install.compose_file.read_text())
        return install, compose

    yield make
    for install in made:
        install.close()


def published(service):
    return [port.split(":", 2) for port in service.get("ports", [])]


def test_rji_01_the_customer_gateway_follows_the_gateway_guide():
    config = customer_gateway("a" * 43, ["coder"], ["cloud"])
    (listener,) = config["binds"][0]["listeners"]
    # The marker is set, never added, before routing.
    assert listener["policies"] == {
        "transformations": {"request": {"set": {"x-keeplane-developer-route": '"1"'}}}
    }
    (route,) = listener["routes"]
    route_check = route["policies"]["extAuthz"]
    assert route_check["protocol"]["http"]["path"] == '"/internal/runtime/authorize"'
    assert route_check["failureMode"] == "deny"
    assert route_check["includeRequestHeaders"] == ["authorization"]
    assert "backendAuth" in route_check["policies"]
    assert route["policies"]["retry"]["attempts"] == 2
    by_model = {}
    for row in config["policies"]:
        model = row["target"]["backend"]["backend"]["name"].removeprefix("llm:model:")
        by_model.setdefault(model, []).append(row["policy"])
    # Every model has the final check first and the strip last.
    assert set(by_model) == {CUSTOMER_MODEL, "coder", "cloud"}
    for model, policies in by_model.items():
        check = policies[0]["extAuthz"]["protocol"]["http"]
        assert FINAL in check["path"] and KEY_ONLY in check["path"], model
        assert json.dumps(model) in check["body"], model
        assert policies[0]["extAuthz"]["failureMode"] == "deny"
        assert "backendAuth" in policies[0]["extAuthz"]["policies"]
        replace = policies[-1]["transformations"]["request"]["replace"]
        kept = "authorization" in replace
        assert kept == (model == "cloud"), model
        assert all(name not in replace for name in FORWARD_NEVER[1:]), model
    # Only the cloud model's backend adds the customer's own provider key.
    assert [
        model
        for model, policies in by_model.items()
        if any("backendAuth" in policy for policy in policies)
    ] == ["cloud"]


def test_rji_02_developers_reach_only_the_one_address_and_the_developer_listener(
    written,
):
    for mode in ("existing", "managed"):
        install, compose = written(mode)
        services = compose["services"]
        ports = {name: published(service) for name, service in services.items()}
        assert {name for name, value in ports.items() if value} == {"app", "gateway"}
        assert ports["app"] == [["127.0.0.1", str(install.app_port), "3000"]]
        # The gateway's management address (4000) is never published.
        assert ports["gateway"] == [["127.0.0.1", str(install.runtime_port), "5000"]]
        environment = services[COPIES[0]]["environment"]
        assert environment["KEEPLANE_GATEWAY_PUBLIC_URL"] == (
            f"http://127.0.0.1:{install.runtime_port}/v1"
        )
        assert environment["GATEWAY_MODE"] == mode
        assert environment["PUBLIC_ORIGIN"] == install.base


def test_rji_03_two_copies_share_one_database_and_signing_secret(written):
    for mode in ("existing", "managed"):
        _, compose = written(mode)
        services = compose["services"]
        first, second = (services[name] for name in COPIES)
        assert first["environment"] == second["environment"]
        assert first["environment"]["KEEPLANE_DATABASE_HOST"] == "database"
        assert first["environment"]["DJANGO_SECRET_KEY_FILE"] == "/trial/signing-key"
        assert services["app"]["command"][-2:] == list(COPIES)
        for name in COPIES:
            assert services[name]["read_only"] and services[name]["cap_drop"] == ["ALL"]


def test_rji_04_the_managed_enroller_reads_with_its_own_read_only_role(written):
    _, compose = written("managed")
    services = compose["services"]
    enroller = services["model-enroller"]
    assert enroller["network_mode"] == "service:gateway"
    assert "ports" not in enroller
    assert enroller["environment"]["KEEPLANE_DATABASE_USER"] == "keeplane_enroller"
    assert enroller["environment"]["KEEPLANE_DATABASE_READ_ONLY"] == "1"
    assert "default_transaction_read_only = on" in release_journey.ENROLLER_ROLE
    assert services["gateway"]["command"] == ["-f", "/installed/gateway.json"]
    _, compose = written("existing")
    assert "model-enroller" not in compose["services"]
    assert compose["services"]["gateway"]["command"] == ["-f", "/trial/gateway.yaml"]


class Copy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        data = json.dumps(
            {
                "copy": self.server.name,
                "host": self.headers["Host"],
                "body": body.decode(),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Set-Cookie", "a=1")
        self.send_header("Set-Cookie", "b=2")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_rji_05_the_one_address_sends_each_request_to_the_next_copy(tmp_path):
    copies, threads = [], []
    for name in COPIES:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Copy)
        server.name = name
        copies.append(server)
    servers = copies + [
        front_server(
            [f"127.0.0.1:{server.server_address[1]}" for server in copies],
            ("127.0.0.1", 0),
            tmp_path / "copies.json",
        )
    ]
    for server in servers:
        threads.append(threading.Thread(target=server.serve_forever, daemon=True))
        threads[-1].start()
    front = servers[-1]
    opener = build_opener(ProxyHandler({}))
    try:
        answers = []
        for number in range(4):
            request = Request(
                f"http://127.0.0.1:{front.server_address[1]}/api/x",
                json.dumps({"n": number}).encode(),
                {"Host": "127.0.0.1:3999"},
            )
            with opener.open(request, timeout=10) as response:
                answers.append(
                    (json.load(response), response.headers.get_all("Set-Cookie"))
                )
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    assert [answer["copy"] for answer, _ in answers] == [*COPIES, *COPIES]
    # The browser's own address and the body reach the copy unchanged, and
    # every cookie comes back.
    assert {answer["host"] for answer, _ in answers} == {"127.0.0.1:3999"}
    assert [json.loads(answer["body"])["n"] for answer, _ in answers] == [0, 1, 2, 3]
    assert all(cookies == ["a=1", "b=2"] for _, cookies in answers)
    counted = json.loads((tmp_path / "copies.json").read_text())
    assert sorted(counted.values()) == [2, 2]
