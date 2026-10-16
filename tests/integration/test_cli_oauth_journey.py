"""Real CLI → Django/Toolkit HTTP; a controlled browser drives native sign-in."""

import hashlib
import importlib.util
import io
import json
import os
import secrets
import uuid
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import ClassVar
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from django.apps import apps
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.test import override_settings
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy
from projects.models import ProjectUse

from tests.fixtures.cli_coding_provider import Handler, start
from tests.integration.test_cli_oauth_browser import browser_flow  # noqa: F401

pytestmark = [
    pytest.mark.optional,
    pytest.mark.live,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not apps.is_installed("oauth2_provider"),
        reason="Install the pinned OAuth trial graph",
    ),
]


class HiddenFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "input" and values.get("type") == "hidden" and "name" in values:
            self.values[values["name"]] = values.get("value", "")


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def signed_in_cli(
    browser_flow,  # noqa: F811 - shared pytest fixture imported above.
    monkeypatch,
    tmp_path,
    capsys,
    request,
    cli_browser_driver,
):
    from accounts import views
    from common import api
    from model_registry import runtime_views

    source = Path(
        os.environ.get("KEEPLANE_CLI_SOURCE", Path(__file__).resolve().parents[2])
    )
    entry = source / "components/cli/keeplane.py"
    if not entry.is_file():
        if "KEEPLANE_CLI_SOURCE" in os.environ:
            pytest.fail("The explicitly configured CLI source is unavailable")
        pytest.skip(
            "Compose the reviewed browser/profile CLI before this optional journey"
        )
    monkeypatch.syspath_prepend(str(entry.parent))
    spec = importlib.util.spec_from_file_location("keeplane_join", entry)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    flow = browser_flow
    model_id = getattr(request, "param", "coder")
    resource = {"id": model_id, "revision": 1, "value": {}}
    flow.domain.catalog.approve(model_id, [], fingerprint(model_id, [resource]))
    gateway = type(
        "Registry",
        (),
        {
            "models": lambda self: (200, {"data": [{"id": model_id}]}),
            "resources": lambda self: (200, {"resources": [resource]}),
        },
    )()
    monkeypatch.setattr(
        runtime_views, "model_policy", lambda: DjangoModelPolicy(gateway)
    )
    observations = []
    application = get_wsgi_application()

    def observed(environ, start_response):
        observations.append((environ["PATH_INFO"], bool(environ.get("HTTP_COOKIE"))))
        return application(environ, start_response)

    http = make_server("127.0.0.1", 0, observed, handler_class=QuietHandler)
    server = f"http://127.0.0.1:{http.server_port}"
    monkeypatch.setattr(api, "PUBLIC_ORIGIN", server)
    monkeypatch.setattr(views, "PUBLIC_ORIGIN", server)
    cookies = CookieJar()
    opener = build_opener(
        ProxyHandler({}), HTTPCookieProcessor(cookies), cli.browser_login.NoRedirects()
    )

    def browser_request(url, data=None, expected=200):
        outgoing = Request(
            url,
            data=None if data is None else urlencode(data).encode(),
            headers={"Origin": server},
        )
        if data is not None:
            outgoing.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with opener.open(outgoing, timeout=5) as response:
                assert response.status == expected
                return response.read(64 * 1024), response.headers
        except HTTPError as error:
            assert error.code == expected
            body, headers = error.read(64 * 1024), error.headers
            error.close()
            return body, headers

    def browser(url):
        _, response = browser_request(url, expected=302)
        return_to = parse_qs(urlsplit(response["Location"]).query)["return_to"][0]
        assert response["Location"].startswith("/sign-in?") and return_to.startswith(
            "/oauth/authorize/?"
        )
        raw, _ = browser_request(server + "/api/auth-options")
        csrf = json.loads(raw)["csrf_token"]
        sign_in = Request(
            server + "/api/session",
            data=json.dumps(
                {
                    "username": "browser-developer",
                    "password": "synthetic-browser-password",
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": server,
                "X-CSRFToken": csrf,
            },
        )
        with opener.open(sign_in, timeout=5) as response:
            assert response.status == 200
        page, _ = browser_request(server + return_to)
        assert b"Allow CLI access?" in page and b"browser-developer" in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["allow"] = "true"
        _, response = browser_request(server + "/oauth/authorize/", form.values, expected=302)
        target = urlsplit(response["Location"])
        assert target.hostname == "127.0.0.1" and target.path == "/callback"
        assert parse_qs(target.query)["iss"] == [server]
        browser_request(response["Location"])
        return True

    thread = Thread(target=http.serve_forever, daemon=True)
    profile = tmp_path / "profile"
    project = str(uuid.uuid4())
    configured = dict(settings.OAUTH2_PROVIDER, OIDC_ISS_ENDPOINT=server)
    try:
        with override_settings(PUBLIC_ORIGIN=server, OAUTH2_PROVIDER=configured):
            thread.start()
            monkeypatch.setattr(cli.browser_login.webbrowser, "open", cli_browser_driver or browser)

            def command(action, *arguments, expected=0):
                monkeypatch.setattr(
                    "sys.argv",
                    ["keeplane", action, "--profile", str(profile), *arguments],
                )
                assert cli.main() == expected
                return capsys.readouterr().out

            assert "Signed in" in command(
                "login", "--server", server, "--timeout", "10"
            )
            with cli.opened(profile) as store:
                credential = store.load()
            assert (
                credential.actor_id == str(flow.owner.pk)
                and credential.issuer == server
            )
            yield SimpleNamespace(cli=cli, flow=flow, command=command,
                                  credential=credential, profile=profile, project=project,
                                  model_id=model_id, gateway=gateway, server=server,
                                  browser_request=browser_request, observations=observations)
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def test_real_client_sign_in_profile_registration_catalog_and_logout(signed_in_cli):
    journey = signed_in_cli
    command, flow = journey.command, journey.flow
    assert json.loads(command("whoami"))["id"] == str(flow.owner.pk)
    assert json.loads(command("register-project", "--project", journey.project,
                              "--name", "Real CLI journey"))["project_id"] == journey.project
    assert ProjectUse.objects.get(project_id=journey.project).user_id == flow.owner.pk
    assert json.loads(command("models", "--project", journey.project))["models"] == [{"id": journey.model_id}]
    assert "removed" in command("logout")
    assert not (journey.profile / "credential.json").exists()
    assert flow.identity.session(journey.credential.access_token) is None
    assert flow.refresh(journey.credential.refresh_token).status_code == 400
    native, _ = journey.browser_request(journey.server + "/api/identity")
    assert json.loads(native)["id"] == str(flow.owner.pk)
    assert any(path == "/oauth/token/" for path, _ in journey.observations)
    assert all(not cookie for path, cookie in journey.observations
               if path == "/oauth/token/" or path.startswith("/api/runtime/"))


@pytest.mark.parametrize("signed_in_cli", ["fixture-coder"], indirect=True)
def test_real_signed_in_coding_tools_resume_and_policy_withdrawal(signed_in_cli, monkeypatch, tmp_path):
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set the pinned native runtime for the complete coding journey")
    assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    from model_registry import runtime_callback

    journey = signed_in_cli
    monkeypatch.setattr(runtime_callback, "IDENTITY", journey.flow.native)
    monkeypatch.setattr(runtime_callback, "MODEL_GATEWAY", journey.gateway)
    monkeypatch.setattr(runtime_callback, "model_policy", lambda: DjangoModelPolicy(journey.gateway))
    key, keyfile = secrets.token_urlsafe(32), tmp_path / "gateway-secret"
    keyfile.write_text(key)
    keyfile.chmod(0o600)
    opener = build_opener(ProxyHandler({}), journey.cli.browser_login.NoRedirects())

    class PolicyProvider(Handler):
        withdraw, accepted = False, 0
        denied: ClassVar[list[int]] = []
        sessions: ClassVar[set[str]] = set()

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            self.rfile = io.BytesIO(raw)
            body = json.loads(raw)
            if self.withdraw:
                journey.flow.domain.catalog.remove(journey.model_id)
                type(self).withdraw = False
            outgoing = Request(journey.server + "/internal/runtime/authorize",
                               data=json.dumps({"project_id": self.headers.get("X-Keeplane-Project-ID"),
                                                "model_id": body.get("model")}).encode(),
                               headers={"Authorization": self.headers.get("Authorization", ""),
                                        "X-Keeplane-Gateway-Credential": key,
                                        "Content-Type": "application/json"})
            try:
                with opener.open(outgoing, timeout=5) as response:
                    assert response.status == 200
                    decision = json.loads(response.read(4096))
                    assert decision == {"actor_id": journey.credential.actor_id,
                                        "project_id": journey.project, "model_id": journey.model_id}
            except HTTPError as error:
                type(self).denied.append(error.code)
                error.close()
                self.send_error(403)
                return
            type(self).accepted += 1
            if body.get("tools"):
                self.sessions.add(self.headers["x-opencode-session-id"])
            super().do_POST()

    directory, state = tmp_path / "repository", tmp_path / "history"
    directory.mkdir()
    target = directory / "math.py"
    target.write_text("def add(a, b):\n    return a - b\n")
    provider = start(target, handler=PolicyProvider, turn_scoped=True)
    thread = Thread(target=provider.serve_forever, daemon=True)
    previous = Handler.grant
    Handler.grant = journey.credential.access_token
    arguments = ["--project", journey.project, "--name", "Real coding journey",
                 "--model", journey.model_id, "--runtime", binary,
                 "--gateway", f"http://127.0.0.1:{provider.server_port}/v1",
                 "--directory", str(directory), "--state-dir", str(state), "--timeout", "40"]
    try:
        with override_settings(RUNTIME_AUTHORIZER_KEY_FILE=str(keyfile)):
            thread.start()
            journey.command("code", *arguments, "Fix the addition function in math.py.")
            assert target.read_text() == "def add(a, b):\n    return a + b\n" and Handler.calls == ["read", "edit"]
            assert len(PolicyProvider.sessions) == 1
            session = next(iter(PolicyProvider.sessions))
            target.write_text("def add(a, b):\n    return a - b\n")
            Handler.calls, Handler.call_prefix = [], "second_"
            journey.command("code", *arguments, "--session", session, "Fix addition again.")
            assert target.read_text() == "def add(a, b):\n    return a + b\n" and Handler.calls == ["read", "edit"]
            assert PolicyProvider.sessions == {session}
            accepted = PolicyProvider.accepted
            target.write_text("def add(a, b):\n    return a - b\n")
            PolicyProvider.withdraw = True
            journey.command("code", *arguments, "--session", session, "Try another edit.", expected=1)
            assert PolicyProvider.accepted == accepted and PolicyProvider.denied == [403]
            assert target.read_text() == "def add(a, b):\n    return a - b\n"
            assert "removed" in journey.command("logout")
            assert journey.flow.identity.session(journey.credential.access_token) is None
            assert journey.flow.refresh(journey.credential.refresh_token).status_code == 400
            old = Request(f"http://127.0.0.1:{provider.server_port}/v1/chat/completions",
                          data=json.dumps({"model": journey.model_id, "messages": []}).encode(),
                          headers={"Authorization": "Bearer " + journey.credential.access_token,
                                   "X-Keeplane-Project-ID": journey.project})
            with pytest.raises(HTTPError) as refused:
                opener.open(old, timeout=5)
            refused.value.close()
            assert PolicyProvider.denied == [403, 401] and PolicyProvider.accepted == accepted
            for path in state.iterdir():
                assert all(value.encode() not in path.read_bytes() for value in
                           (journey.credential.access_token, journey.credential.refresh_token, key))
    finally:
        Handler.grant = previous
        if thread.is_alive():
            provider.shutdown()
        provider.server_close()
        thread.join(timeout=5)
