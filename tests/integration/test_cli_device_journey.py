"""Device CLI → real Django/Toolkit HTTP; controlled human code entry and consent."""

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
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.test import override_settings
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy
from projects.models import ProjectUse

try:
    from tests.integration.test_cli_oauth_browser import browser_flow
except ImportError:
    if os.environ.get("KEEPLANE_DEVICE_JOURNEY_REQUIRED") == "1":
        raise RuntimeError(
            "Compose the reviewed browser/device issuer server"
        ) from None
    browser_flow = None

if os.environ.get("KEEPLANE_DEVICE_JOURNEY_REQUIRED") == "1" and not apps.is_installed(
    "oauth2_provider"
):
    raise RuntimeError("Install the pinned OAuth trial graph for the required journey")

pytestmark = [
    pytest.mark.optional,
    pytest.mark.skipif(
        browser_flow is None, reason="Compose the reviewed browser/device issuer server"
    ),
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


def test_real_device_client_profile_registration_catalog_and_logout(
    browser_flow,
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
    call_command("register_cli_client", device=True, verbosity=0)
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

    def approve(message):
        print(message)
        user_code = message.split("enter code ")[1].rstrip(".")
        url = server + "/oauth/confirm-device/?" + urlencode({"user_code": user_code})
        _, response = request(url, expected=302)
        return_to = parse_qs(urlsplit(response["Location"]).query)["return_to"][0]
        assert return_to.startswith("/oauth/confirm-device/?")
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
        assert b"Connect your CLI" in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["user_code"] = user_code
        _, response = request(
            server + "/oauth/confirm-device/", form.values, expected=302
        )
        page, _ = request(server + response["Location"])
        assert b"Allow CLI access?" in page and b"browser-developer" in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["action"] = "accept"
        page, _ = request(server + "/oauth/confirm-device/", form.values)
        assert b"CLI access allowed" in page

    thread = Thread(target=http.serve_forever, daemon=True)
    profile = tmp_path / "profile"
    project = str(uuid.uuid4())
    configured = dict(
        settings.OAUTH2_PROVIDER,
        OIDC_ISS_ENDPOINT=server,
        OAUTH_DEVICE_VERIFICATION_URI=server + "/oauth/confirm-device/",
        OAUTH_DEVICE_VERIFICATION_URI_COMPLETE=server
        + "/oauth/confirm-device/?user_code={user_code}",
    )
    try:
        with override_settings(PUBLIC_ORIGIN=server, OAUTH2_PROVIDER=configured):
            thread.start()
            original_login = cli.device_login.login
            original_start = cli.device_login.start
            sources = []

            def login(*args, **kwargs):
                return original_login(*args, **kwargs, announce=approve)

            def start(*args, **kwargs):
                value = original_start(*args, **kwargs)
                sources.append(value[1])
                return value

            monkeypatch.setattr(cli.device_login, "login", login)
            monkeypatch.setattr(cli.device_login, "start", start)

            def command(action, *arguments):
                monkeypatch.setattr(
                    "sys.argv",
                    ["keeplane", action, "--profile", str(profile), *arguments],
                )
                assert cli.main() == 0
                return capsys.readouterr().out

            assert "Signed in" in command(
                "login", "--device", "--server", server, "--timeout", "20"
            )
            with cli.opened(profile) as store:
                credential = store.load()
            assert (
                credential.actor_id == str(flow.owner.pk)
                and credential.issuer == server
            )
            assert (
                len(sources) == 1
                and sources[0].encode()
                not in (profile / "credential.json").read_bytes()
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
            with pytest.raises(cli.ConnectionError):
                cli.browser_login.exchange(
                    server,
                    {
                        "grant_type": "refresh_token",
                        "client_id": "keeplane-cli-device",
                        "refresh_token": credential.refresh_token,
                    },
                )
            native, _ = request(server + "/api/identity")
            assert json.loads(native)["id"] == str(flow.owner.pk)
            assert any(path == "/oauth/token/" for path, _ in observations)
            assert all(
                not cookie
                for path, cookie in observations
                if path in {"/oauth/device/", "/oauth/token/"}
                or path.startswith("/api/runtime/")
            )
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        thread.join(timeout=5)
