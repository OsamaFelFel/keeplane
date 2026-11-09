"""Spec 009 ST29 against the real sign-in server: an expired token sends nothing.

The plain-English cases are in cli-sign-in-again-cases.md next to this file.
"""

import io
import json
import sys
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import pytest
from django.apps import apps

from tests.integration.test_cli_oauth_browser import browser_flow  # noqa: F401
from tests.integration.test_cli_oauth_journey import HiddenFields, signed_in_cli  # noqa: F401

pytestmark = [
    pytest.mark.optional,
    pytest.mark.live,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not apps.is_installed("oauth2_provider"),
        reason="Install the pinned OAuth trial graph",
    ),
]

SCRIPT = (
    "Your Keeplane sign-in has expired, so nothing was sent. "
    "Run `keeplane login` to sign in again.\n"
)


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def gateway():
    """A stand-in gateway that records every request it receives."""
    seen = []

    class Recorder(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append(self.path)
            self.send_error(500)

        do_GET = do_POST

    http = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/v1", seen
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)


@pytest.fixture
def runtime(tmp_path):
    """A runtime that answers the version check and records each coding turn."""
    started = tmp_path / "turns"
    binary = tmp_path / "opencode"
    binary.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo 2.0.27; exit 0; fi\n'
        f'echo turn >> "{started}"\n'
        'echo \'{"type": "text", "part": {"text": "Done."}}\'\n'
    )
    binary.chmod(0o700)
    return binary, started


def run(journey, monkeypatch, capsys, *arguments):
    """Run the CLI and keep both outputs (the shared helper keeps only stdout)."""
    monkeypatch.setattr(
        "sys.argv",
        ["keeplane", arguments[0], "--profile", str(journey.profile), *arguments[1:]],
    )
    status = journey.cli.main()
    return status, capsys.readouterr()


def expire():
    """Age the one CLI access token past its 8 hours, as the clock would."""
    from django.utils import timezone
    from oauth2_provider.models import AccessToken

    assert (
        AccessToken.objects.update(expires=timezone.now() - timedelta(seconds=1)) == 1
    )


def test_exp_int_01_an_expired_token_sends_nothing_and_signs_in_again_on_yes(
    signed_in_cli,  # noqa: F811
    gateway,
    runtime,
    monkeypatch,
    tmp_path,
    capsys,
):
    from model_registry.model_choice import DjangoModelChoice

    journey = signed_in_cli
    address, seen = gateway
    # No gateway runs here, so the model's live setup check is taken as passed.
    monkeypatch.setattr(DjangoModelChoice, "_usable", lambda self, owner, model: True)
    directory = tmp_path / "repository"
    directory.mkdir()
    expire()
    arguments = [
        "--project",
        journey.project,
        "--name",
        "Expired journey",
        "--model",
        journey.model_id,
        "--runtime",
        str(runtime[0]),
        "--gateway",
        address,
        "--directory",
        str(directory),
        "anything",
    ]

    # In a script: exit 1, name `keeplane login`, nothing reaches the gateway.
    journey.observations.clear()
    status, output = run(journey, monkeypatch, capsys, "code", *arguments)
    assert status == 1 and output.err == SCRIPT
    assert [path for path, _ in journey.observations] == ["/api/runtime/session"]
    assert seen == [] and not runtime[1].exists()

    # In a terminal: yes signs in again with the saved server, yes starts the task.
    def consent(url):
        page, _ = journey.browser_request(url)
        assert b"Allow CLI access?" in page
        form = HiddenFields()
        form.feed(page.decode())
        form.values["allow"] = "true"
        _, response = journey.browser_request(
            journey.server + "/oauth/authorize/", form.values, expected=302
        )
        assert urlsplit(response["Location"]).path == "/callback"
        journey.browser_request(response["Location"])
        return True

    monkeypatch.setattr(journey.cli.browser_login.webbrowser, "open", consent)
    monkeypatch.setattr(sys, "stdin", Terminal("y\ny\n"))
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True, raising=False)
    status, output = run(journey, monkeypatch, capsys, "code", *arguments)
    assert status == 0, output.err
    assert output.err.startswith(
        "Your Keeplane sign-in has expired, so nothing was sent. Sign in again now? [Y/n] "
    )
    assert "Signed in. Start the task now? [Y/n] " in output.err
    assert json.loads(output.out.splitlines()[-1])["part"]["text"] == "Done."
    assert runtime[1].read_text() == "turn\n"
    with journey.cli.opened(journey.profile) as store:
        renewed = store.load()
    assert (
        renewed.issuer == journey.server
        and renewed.actor_id == journey.credential.actor_id
    )
    assert renewed.access_token != journey.credential.access_token
    assert journey.flow.identity.session(renewed.access_token) is not None
    assert (
        seen == []
    )  # The stand-in runtime never calls it; the first run sent nothing.


def test_exp_int_02_signed_out_sends_nothing(
    signed_in_cli,  # noqa: F811
    gateway,
    runtime,
    monkeypatch,
    tmp_path,
    capsys,
):
    journey = signed_in_cli
    address, seen = gateway
    assert "removed" in journey.command("logout")
    journey.observations.clear()
    status, output = run(
        journey,
        monkeypatch,
        capsys,
        "code",
        "--project",
        str(uuid.uuid4()),
        "--model",
        journey.model_id,
        "--runtime",
        str(runtime[0]),
        "--gateway",
        address,
        "--directory",
        str(tmp_path),
        "anything",
    )
    assert status == 1 and output.err == (
        "You're signed out of Keeplane, so nothing was sent. "
        "Run `keeplane login` to sign in.\n"
    )
    assert journey.observations == [] and seen == [] and not runtime[1].exists()
