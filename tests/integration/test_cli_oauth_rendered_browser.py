"""Actual React sign-in, consent and CLI callback with a disposable account."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from django.apps import apps

from tests.integration.test_cli_oauth_browser import browser_flow  # noqa: F401
from tests.integration.test_cli_oauth_journey import signed_in_cli  # noqa: F401

pytestmark = [pytest.mark.optional, pytest.mark.live, pytest.mark.django_db(transaction=True),
              pytest.mark.skipif(not apps.is_installed("oauth2_provider"),
                                 reason="Install the pinned OAuth trial graph")]


@pytest.fixture
def cli_browser_driver(settings):
    node, ui = os.environ.get("KEEPLANE_BROWSER_NODE"), os.environ.get("KEEPLANE_BROWSER_UI")
    if not node or not ui:
        pytest.skip("Set KEEPLANE_BROWSER_NODE and KEEPLANE_BROWSER_UI for rendered sign-in")
    directory = Path(ui)
    assert (directory / "dist/index.html").is_file(), "The configured React build is unavailable"
    assert Path(node).is_file(), "The configured Node runtime is unavailable"
    settings.ADMIN_UI_DIR = directory
    script = Path(__file__).resolve().parents[1] / "browser/cli-oauth-browser.mjs"

    def browser(url):
        result = subprocess.run([node, str(script), url], capture_output=True, text=True,
                                timeout=25, check=False)
        assert result.returncode == 0, "Rendered sign-in failed; no browser details are printed"
        assert json.loads(result.stdout) == {"sign_in": True, "consent": True, "callback": True}
        return True

    return browser


def test_rendered_react_sign_in_returns_to_consent_and_cli(signed_in_cli):  # noqa: F811
    journey = signed_in_cli
    assert json.loads(journey.command("whoami"))["id"] == journey.credential.actor_id
    assert json.loads(journey.command("register-project", "--project", journey.project,
                                     "--name", "Rendered browser journey"))["project_id"] == journey.project
    assert json.loads(journey.command("models", "--project", journey.project))["models"] == [{"id": journey.model_id}]
    assert "removed" in journey.command("logout")
    assert journey.flow.identity.session(journey.credential.access_token) is None
    assert journey.flow.refresh(journey.credential.refresh_token).status_code == 400
    paths = {path for path, _ in journey.observations}
    assert {"/sign-in", "/api/session", "/oauth/authorize/", "/oauth/token/"} <= paths
    assert any(path.startswith(("/assets/", "/app/assets/")) for path in paths)
    assert all(not cookie for path, cookie in journey.observations
               if path == "/oauth/token/" or path.startswith("/api/runtime/"))
