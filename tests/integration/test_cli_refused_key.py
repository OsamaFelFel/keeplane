"""Spec 004 ST11 "A refused key", from the CLI to the provider fixture and back.

Cases: tests/integration/cli-refused-key-cases.md (RK-INT-01 to RK-INT-03). After a
task's 401 or 403, the CLI's own request code (``server_connection.request``)
asks the real Django key routes, over HTTP on a threaded local server, to
recheck the saved key. The server checks it with the authenticated provider
fixture, which turns the key down, and `keeplane keys list` then shows it as
refused.
"""

import uuid
from threading import Thread
from types import SimpleNamespace
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from django.core.wsgi import get_wsgi_application
from django.test import override_settings
from model_registry import runtime_keys
from model_registry.models import DeveloperProviderKey
from projects.services import DjangoProjectStore

from components.cli import provider_keys
from tests.integration.test_provider_key_validation import provider  # noqa: F401
from tests.integration.test_runtime_provider_keys import (  # noqa: F401
    api,
    fixture_password_hashes,
    put,
    safe,
)

pytestmark = pytest.mark.django_db(transaction=True)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def cli(api, monkeypatch):  # noqa: F811
    """The developer's saved key, their project, and the routes over HTTP."""
    safe(put(api))
    actor = api.identity.session(api.tokens[0])
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(actor["id"], project, "Refused key")
    monkeypatch.setattr(
        runtime_keys.runtime_views,
        "model_policy",
        lambda: SimpleNamespace(eligible_model_ids=lambda _: frozenset({"model"})),
    )
    http = make_server(
        "127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler
    )
    address = f"http://127.0.0.1:{http.server_port}"
    thread = Thread(target=http.serve_forever, daemon=True)
    try:
        with override_settings(ALLOWED_HOSTS=["127.0.0.1", "testserver"]):
            thread.start()
            yield SimpleNamespace(api=api, issuer=address, project=project)
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def recheck(f, token=None):
    return provider_keys.refused_after_failure(
        f.issuer, token or f.api.tokens[0], f.project, "model"
    )


def listed(f):
    """What `keeplane keys list` prints, read with the CLI's own code.

    These accounts sign in with a session, not a CLI profile, so the key list
    is read without one; `list_keys` only adds the profile's account check.
    """
    return provider_keys.key_rows(f.issuer, f.api.tokens[0], f.project)["models"]


def test_rk_int_01_a_key_the_provider_turns_down_shows_as_refused(cli):
    calls = cli.api.provider["calls"]
    assert len(calls) == 1  # Adding the key checked it once.
    assert listed(cli) == [{"id": "model", "own_key_required": True, "status": "added"}]
    cli.api.provider["mode"] = 401
    assert recheck(cli) is True
    # One provider request, with the saved key; nothing came back to the CLI.
    assert len(calls) == 2 and calls[-1]["key_matches"]
    assert listed(cli) == [
        {"id": "model", "own_key_required": True, "status": "refused"}
    ]
    assert DeveloperProviderKey.objects.get().refused
    # Already refused: the next failed task needs no new provider request.
    assert recheck(cli) is True and len(calls) == 2


def test_rk_int_01_a_403_from_the_provider_is_a_refusal_too(cli):
    cli.api.provider["mode"] = 403
    assert recheck(cli) is True
    assert listed(cli)[0]["status"] == "refused"


def test_rk_int_02_a_key_the_provider_still_accepts_stays_added(cli):
    assert recheck(cli) is False
    assert len(cli.api.provider["calls"]) == 2
    assert listed(cli)[0]["status"] == "added"
    # A provider outage records no verdict either.
    cli.api.provider["mode"] = 500
    assert recheck(cli) is False
    assert listed(cli)[0]["status"] == "added"


def test_rk_int_03_an_ended_sign_in_contacts_no_provider(cli):
    cli.api.identity.logout(cli.api.tokens[0])
    cli.api.provider["mode"] = 401
    assert recheck(cli) is False
    assert len(cli.api.provider["calls"]) == 1
    assert not DeveloperProviderKey.objects.get().refused
