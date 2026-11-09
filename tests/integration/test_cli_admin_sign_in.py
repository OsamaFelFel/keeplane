"""Spec 009 ST29 "An admin signs in" and "Sign out" against the real sign-in server.

D188, ADR 028, ADR 018; journey cases DEV-05, DEV-06 and DEV-08. The
plain-English cases are in cli-admin-sign-in-cases.md next to this file. The
real CLI talks HTTP to Django and Django OAuth Toolkit; a controlled browser
signs in and allows access. A stand-in gateway records every request it gets
and a stand-in runtime records each coding turn.
"""

import json
import uuid
from http.cookiejar import CookieJar
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from wsgiref.simple_server import make_server

import pytest
from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.test import override_settings
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy

from components.cli import browser_login, device_login, keeplane
from components.cli.credential_profile import opened
from tests.integration.test_cli_oauth_browser import browser_flow  # noqa: F401
from tests.integration.test_cli_oauth_journey import HiddenFields, QuietHandler
from tests.integration.test_cli_sign_in_again import gateway, runtime  # noqa: F401

pytestmark = [
    pytest.mark.optional,
    pytest.mark.live,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not apps.is_installed("oauth2_provider"),
        reason="Install the pinned OAuth trial graph",
    ),
]

DEVICE_LOGIN = device_login.login
SIGNED_OUT = (
    "You're signed out of Keeplane, so nothing was sent. "
    "Run `keeplane login` to sign in.\n"
)


@pytest.fixture
def server(browser_flow, monkeypatch, tmp_path):  # noqa: F811
    """The real routes on a local HTTP server, with one approved model."""
    from accounts import views
    from common import api
    from model_registry import runtime_views
    from model_registry.model_choice import DjangoModelChoice

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    flow = browser_flow
    call_command("register_cli_client", device=True, verbosity=0)
    resource = {"id": "coder", "revision": 1, "value": {}}
    flow.domain.catalog.approve("coder", [], fingerprint("coder", [resource]))
    registry = type(
        "Registry",
        (),
        {
            "models": lambda self: (200, {"data": [{"id": "coder"}]}),
            "resources": lambda self: (200, {"resources": [resource]}),
        },
    )()
    monkeypatch.setattr(
        runtime_views, "model_policy", lambda: DjangoModelPolicy(registry)
    )
    # No gateway runs here, so the model's live setup check is taken as passed.
    monkeypatch.setattr(DjangoModelChoice, "_usable", lambda self, owner, model: True)
    observations = []
    application = get_wsgi_application()

    def observed(environ, start_response):
        observations.append(environ["PATH_INFO"])
        return application(environ, start_response)

    http = make_server("127.0.0.1", 0, observed, handler_class=QuietHandler)
    address = f"http://127.0.0.1:{http.server_port}"
    monkeypatch.setattr(api, "PUBLIC_ORIGIN", address)
    monkeypatch.setattr(views, "PUBLIC_ORIGIN", address)
    configured = dict(
        settings.OAUTH2_PROVIDER,
        OIDC_ISS_ENDPOINT=address,
        OAUTH_DEVICE_VERIFICATION_URI=address + "/oauth/confirm-device/",
        OAUTH_DEVICE_VERIFICATION_URI_COMPLETE=address
        + "/oauth/confirm-device/?user_code={user_code}",
    )
    thread = Thread(target=http.serve_forever, daemon=True)
    try:
        with override_settings(PUBLIC_ORIGIN=address, OAUTH2_PROVIDER=configured):
            thread.start()
            yield SimpleNamespace(flow=flow, address=address, observations=observations)
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def person(server, role):
    """A browser for the first admin or a developer, and its account."""
    if role == "admin":
        username = "first-admin"
        password = server.flow.domain.secret.read_text().strip()
    else:
        username, password = "browser-developer", "synthetic-browser-password"
    opener = build_opener(
        ProxyHandler({}), HTTPCookieProcessor(CookieJar()), browser_login.NoRedirects()
    )

    def request(url, data=None, expected=200):
        outgoing = Request(
            url,
            data=None if data is None else urlencode(data).encode(),
            headers={"Origin": server.address},
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

    def sign_in(return_to):
        raw, _ = request(server.address + "/api/auth-options")
        sign_in = Request(
            server.address + "/api/session",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": server.address,
                "X-CSRFToken": json.loads(raw)["csrf_token"],
            },
        )
        with opener.open(sign_in, timeout=5) as response:
            assert response.status == 200
        page, _ = request(server.address + return_to)
        return page

    def browser(url):
        _, response = request(url, expected=302)
        return_to = parse_qs(urlsplit(response["Location"]).query)["return_to"][0]
        page = sign_in(return_to)
        assert b"Allow CLI access?" in page and username.encode() in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["allow"] = "true"
        _, response = request(
            server.address + "/oauth/authorize/", form.values, expected=302
        )
        request(response["Location"])
        return True

    def approve(message):
        # What the developer reads in the terminal, then types in another browser.
        print(message)
        if "enter code " not in message:
            return
        user_code = message.split("enter code ")[1].rstrip(".")
        url = (
            server.address
            + "/oauth/confirm-device/?"
            + urlencode({"user_code": user_code})
        )
        _, response = request(url, expected=302)
        return_to = parse_qs(urlsplit(response["Location"]).query)["return_to"][0]
        page = sign_in(return_to)
        assert b"Connect your CLI" in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["user_code"] = user_code
        _, response = request(
            server.address + "/oauth/confirm-device/", form.values, expected=302
        )
        page, _ = request(server.address + response["Location"])
        assert b"Allow CLI access?" in page and username.encode() in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["action"] = "accept"
        page, _ = request(server.address + "/oauth/confirm-device/", form.values)
        assert b"CLI access allowed" in page

    from accounts.models import User

    return SimpleNamespace(
        username=username,
        account=User.objects.get(username=username),
        browser=browser,
        approve=approve,
    )


def run(monkeypatch, capsys, profile, *arguments):
    monkeypatch.setattr(
        "sys.argv",
        ["keeplane", arguments[0], "--profile", str(profile), *arguments[1:]],
    )
    status = keeplane.main()
    return status, capsys.readouterr()


def sign_in(server, who, how, monkeypatch, capsys, profile, *, named=True):
    """`keeplane login` with a browser, or on a machine with none (DEV-06)."""
    if how == "browser":
        monkeypatch.setattr(browser_login, "no_browser", lambda: None)
        monkeypatch.setattr(browser_login.webbrowser, "open", who.browser)
    else:
        monkeypatch.setattr(browser_login, "no_browser", lambda: "ssh")

        def never(url):
            raise AssertionError("no browser may be opened")

        monkeypatch.setattr(browser_login.webbrowser, "open", never)
        monkeypatch.setattr(
            device_login,
            "login",
            lambda *args, **kwargs: DEVICE_LOGIN(
                *args, **{**kwargs, "announce": who.approve}
            ),
        )
    # Without --server, login uses the server kept at sign-out.
    named_server = ["--server", server.address] if named else []
    status, output = run(
        monkeypatch, capsys, profile, "login", *named_server, "--timeout", "20"
    )
    assert status == 0, output.err
    assert output.out.endswith("Signed in to Keeplane.\n")
    if how == "device":
        assert browser_login.NO_BROWSER in output.out
        assert "/oauth/confirm-device/ and enter code " in output.out
    with opened(profile) as store:
        credential = store.load()
    assert credential.actor_id == str(who.account.pk)
    assert credential.client_id == (
        device_login.CLIENT_ID if how == "device" else "keeplane-cli"
    )
    return credential


def code(monkeypatch, capsys, profile, project, model, runtime, address, directory):  # noqa: F811
    return run(
        monkeypatch,
        capsys,
        profile,
        "code",
        "--project",
        project,
        "--name",
        "Admin journey",
        "--model",
        model,
        "--runtime",
        str(runtime[0]),
        "--gateway",
        address,
        "--directory",
        str(directory),
        "anything",
    )


# ADM-INT-01 to ADM-INT-04
@pytest.mark.parametrize("how", ["browser", "device"])
@pytest.mark.parametrize("role", ["admin", "developer"])
def test_adm_int_01_admins_and_developers_sign_in_and_code_within_the_same_limits(
    server,
    gateway,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    role,
    how,
):
    who = person(server, role)
    profile = tmp_path / "profile"
    sign_in(server, who, how, monkeypatch, capsys, profile)
    status, output = run(monkeypatch, capsys, profile, "whoami")
    assert status == 0 and json.loads(output.out)["role"] == role

    project = str(uuid.uuid4())
    status, output = run(
        monkeypatch,
        capsys,
        profile,
        "register-project",
        "--project",
        project,
        "--name",
        "Admin journey",
    )
    assert status == 0, output.err
    status, output = run(monkeypatch, capsys, profile, "models", "--project", project)
    assert status == 0 and [row["id"] for row in json.loads(output.out)["models"]] == [
        "coder"
    ]

    # The same model limits: a model the project doesn't allow is refused.
    status, output = run(
        monkeypatch, capsys, profile, "use", "--project", project, "elsewhere"
    )
    assert (
        status == 1
        and output.err == keeplane.NOT_ALLOWED.format(model="elsewhere") + "\n"
    )

    address, _ = gateway
    directory = tmp_path / "repository"
    directory.mkdir()
    status, output = code(
        monkeypatch, capsys, profile, project, "elsewhere", runtime, address, directory
    )
    assert status == 1 and not runtime[1].exists(), output.err
    status, output = code(
        monkeypatch, capsys, profile, project, "coder", runtime, address, directory
    )
    assert status == 0, output.err
    assert runtime[1].read_text() == "turn\n"


# ADM-INT-05 and ADM-INT-06
@pytest.mark.parametrize("how", ["browser", "device"])
def test_adm_int_05_after_sign_out_nothing_more_is_sent_until_signing_in_again(
    server,
    gateway,  # noqa: F811
    runtime,  # noqa: F811
    monkeypatch,
    tmp_path,
    capsys,
    how,
):
    who = person(server, "developer")
    profile = tmp_path / "profile"
    credential = sign_in(server, who, how, monkeypatch, capsys, profile)
    project = str(uuid.uuid4())
    status, output = run(monkeypatch, capsys, profile, "logout")
    assert status == 0, output.err
    assert server.flow.identity.session(credential.access_token) is None
    # Only the non-secret server address is kept.
    assert {item.name for item in profile.iterdir()} == {"lock", "server.json"}
    assert json.loads((profile / "server.json").read_text())["server"] == (
        server.address
    )

    address, seen = gateway
    directory = tmp_path / "repository"
    directory.mkdir()
    server.observations.clear()
    status, output = code(
        monkeypatch, capsys, profile, project, "coder", runtime, address, directory
    )
    assert status == 1 and output.err == SIGNED_OUT
    for command in (("models", "--project", project), ("usage",)):
        status, output = run(monkeypatch, capsys, profile, *command)
        assert status == 1 and output.err == SIGNED_OUT
    for command in ("whoami", "refresh"):
        status, output = run(monkeypatch, capsys, profile, command)
        assert status == 1 and output.err == (
            "You're signed out of Keeplane. Run `keeplane login` to sign in.\n"
        )
    assert server.observations == [] and seen == [] and not runtime[1].exists()

    # Signing in again (from a fresh browser) lets the same command through.
    sign_in(
        server,
        person(server, "developer"),
        how,
        monkeypatch,
        capsys,
        profile,
        named=False,
    )
    status, output = code(
        monkeypatch, capsys, profile, project, "coder", runtime, address, directory
    )
    assert status == 0, output.err
    assert runtime[1].read_text() == "turn\n"
