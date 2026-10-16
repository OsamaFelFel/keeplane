"""Real CLI → Django/Toolkit HTTP; a controlled browser drives native sign-in."""

import importlib.util
import json
import os
import uuid
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from threading import Thread
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


def test_real_client_sign_in_profile_registration_catalog_and_logout(
    browser_flow,  # noqa: F811 - shared pytest fixture imported above.
    monkeypatch,
    tmp_path,
    capsys,
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
    resource = {"id": "coder", "revision": 1, "value": {}}
    flow.domain.catalog.approve("coder", [], fingerprint("coder", [resource]))
    gateway = type(
        "Registry",
        (),
        {
            "models": lambda self: (200, {"data": [{"id": "coder"}]}),
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

    def request(url, data=None, expected=200):
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
        _, response = request(url, expected=302)
        return_to = parse_qs(urlsplit(response["Location"]).query)["return_to"][0]
        assert response["Location"].startswith("/sign-in?") and return_to.startswith(
            "/oauth/authorize/?"
        )
        raw, _ = request(server + "/api/auth-options")
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
        page, _ = request(server + return_to)
        assert b"Allow CLI access?" in page and b"browser-developer" in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["allow"] = "true"
        _, response = request(server + "/oauth/authorize/", form.values, expected=302)
        target = urlsplit(response["Location"])
        assert target.hostname == "127.0.0.1" and target.path == "/callback"
        assert parse_qs(target.query)["iss"] == [server]
        request(response["Location"])
        return True

    thread = Thread(target=http.serve_forever, daemon=True)
    profile = tmp_path / "profile"
    project = str(uuid.uuid4())
    configured = dict(settings.OAUTH2_PROVIDER, OIDC_ISS_ENDPOINT=server)
    try:
        with override_settings(PUBLIC_ORIGIN=server, OAUTH2_PROVIDER=configured):
            thread.start()
            monkeypatch.setattr(cli.browser_login.webbrowser, "open", browser)

            def command(action, *arguments):
                monkeypatch.setattr(
                    "sys.argv",
                    ["keeplane", action, "--profile", str(profile), *arguments],
                )
                assert cli.main() == 0
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
            assert json.loads(command("whoami"))["id"] == str(flow.owner.pk)
            assert (
                json.loads(
                    command(
                        "register-project",
                        "--project",
                        project,
                        "--name",
                        "Real CLI journey",
                    )
                )["project_id"]
                == project
            )
            assert ProjectUse.objects.get(project_id=project).user_id == flow.owner.pk
            assert json.loads(command("models", "--project", project))["models"] == [
                {"id": "coder"}
            ]
            assert "removed" in command("logout")
            assert not (profile / "credential.json").exists()
            assert flow.identity.session(credential.access_token) is None
            assert flow.refresh(credential.refresh_token).status_code == 400
            native, _ = request(server + "/api/identity")
            assert json.loads(native)["id"] == str(flow.owner.pk)
            assert any(path == "/oauth/token/" for path, _ in observations)
            assert all(
                not cookie
                for path, cookie in observations
                if path == "/oauth/token/" or path.startswith("/api/runtime/")
            )
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        thread.join(timeout=5)
