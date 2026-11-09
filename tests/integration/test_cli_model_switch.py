"""The CLI's `keeplane use` switch on the real server (Spec 004 ST17).

Cases: tests/integration/cli-model-switch-cases.md (CSW-01 to CSW-07). The CLI's
own request code (``server_connection.request``) reaches the real Django
runtime routes over HTTP on a threaded local server, as the repo project cases
do. The accounts, policy and enrollment files are those of the task routing
cases: a Confidential project with `private` (the developer's own key),
`public` and `outside`.
"""

from threading import Thread
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from common import api
from django.core.wsgi import get_wsgi_application
from django.test import override_settings
from model_registry.models import ModelApproval

from components.cli import coding, keeplane, server_connection, settings_file
from components.cli.server_connection import ConnectionError, SignInExpired
from tests.integration.test_model_choice import choice  # noqa: F401
from tests.integration.test_task_routing import rule, task  # noqa: F401

pytest_plugins = ("tests.integration.test_installed_personal_runtime",)
pytestmark = pytest.mark.django_db(transaction=True)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def cli(task, monkeypatch, tmp_path):  # noqa: F811
    """The real routes on a local HTTP server; the CLI's settings in tmp_path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    sent = []
    real = server_connection.request

    def observed(*args, **kwargs):
        sent.append((args[1], kwargs.get("query")))
        return real(*args, **kwargs)

    # Only observed: every request still goes through the CLI's own code.
    monkeypatch.setattr(coding, "request", observed)
    http = make_server(
        "127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler
    )
    address = f"http://127.0.0.1:{http.server_port}"
    monkeypatch.setattr(api, "PUBLIC_ORIGIN", address)
    thread = Thread(target=http.serve_forever, daemon=True)
    try:
        with override_settings(
            PUBLIC_ORIGIN=address, ALLOWED_HOSTS=["127.0.0.1", "testserver"]
        ):
            thread.start()
            task.issuer, task.sent = address, sent
            yield task
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def allowed(f):
    listing = server_connection.models(f.issuer, f.project, f.token)
    return {row["id"] for row in listing["models"]}


def marks(f):
    notices = []
    listing = keeplane.marked(f.issuer, f.project, f.token, notices.append)
    current = [row["id"] for row in listing["models"] if row["current"]]
    return current, listing["chosen_by"], notices


def test_csw_01_the_switch_beats_the_persona_rule_and_the_level(cli):
    rule(cli, "architect", "public")
    cli.stores.catalog.change_level("complex", "outside", {"outside"})
    # Without a switch the persona rule decides.
    picked = coding.task_model(
        cli.issuer, cli.project, cli.token, persona="architect", level="complex"
    )
    assert (picked["model_id"], picked["chosen_by"]) == ("public", "persona_rule")
    # The CLI sends the switch as the route's model ID, and it wins.
    switched = coding.task_model(
        cli.issuer,
        cli.project,
        cli.token,
        "private",
        persona="architect",
        level="complex",
    )
    assert (switched["model_id"], switched["chosen_by"]) == ("private", "developer")
    assert cli.sent[-1][1] == {
        "model_id": "private",
        "persona": "architect",
        "level": "complex",
    }


def test_csw_02_a_saved_switch_is_what_code_uses(cli):
    settings_file.set_project_model(cli.project, "public")
    notices = []
    model = coding.routed_model(
        cli.issuer, cli.project, cli.token, allowed(cli), notices.append
    )
    assert model == "public"
    assert notices == [coding.USING_SWITCH.format(model="public")]
    settings_file.set_project_model(cli.project, None)
    notices.clear()
    model = coding.routed_model(
        cli.issuer, cli.project, cli.token, allowed(cli), notices.append
    )
    assert notices == [coding.USING_PICK.format(model=model)]


def test_csw_03_a_model_the_project_doesnt_allow_is_refused(cli):
    ModelApproval.objects.filter(pk="outside").update(approved_classes=["Public"])
    # `keeplane use` checks this list, so the switch can't be saved.
    assert "outside" not in allowed(cli)
    rule(cli, "architect", "public")
    settings_file.set_project_model(cli.project, "outside")
    refused = coding.SWITCH_NOT_ALLOWED.format(
        model="outside", sent=coding.NOTHING_SENT
    )
    # A switch saved before the class changed: the CLI's own list stops it...
    with pytest.raises(ConnectionError) as stopped:
        coding.routed_model(cli.issuer, cli.project, cli.token, allowed(cli), print)
    assert str(stopped.value) == refused
    # ...and with a list from before the change, the server's 403 over HTTP
    # does, with no persona rule or level in its place.
    with pytest.raises(ConnectionError) as stopped:
        coding.routed_model(cli.issuer, cli.project, cli.token, {"outside"}, print)
    assert str(stopped.value) == refused and stopped.value.status == 403


def test_csw_04_without_a_usable_own_key_the_server_moves_the_switch(cli):
    rule(cli, "architect", "public")
    cli.store.remove("private")
    settings_file.set_project_model(cli.project, "private")
    notices = []
    model = coding.routed_model(
        cli.issuer, cli.project, cli.token, allowed(cli), notices.append
    )
    assert model == "outside"  # The first allowed model: the CLI names no persona.
    assert notices == [
        (
            "Your own key for private is missing, so this task uses outside. "
            "Run `keeplane keys list` to see your keys."
        )
    ]
    assert settings_file.project_model(cli.project) == "private"


def test_csw_05_models_marks_what_the_next_task_uses(cli):
    assert marks(cli) == (["outside"], "keeplane", [])
    settings_file.set_project_model(cli.project, "public")
    assert marks(cli) == (["public"], "you", [])
    # With the own key gone, the mark follows the task and says why.
    settings_file.set_project_model(cli.project, "private")
    cli.store.remove("private")
    assert marks(cli) == (
        ["outside"],
        "keeplane",
        [
            (
                "Your own key for private is missing, so your next task uses outside. "
                "Run `keeplane keys list` to see your keys."
            )
        ],
    )
    # A switch the project no longer allows is named, and nothing is marked.
    ModelApproval.objects.filter(pk="public").update(approved_classes=["Public"])
    settings_file.set_project_model(cli.project, "public")
    assert marks(cli) == (
        [],
        None,
        [coding.SWITCH_NOT_ALLOWED.format(model="public", sent="")],
    )


def test_csw_06_a_project_refusal_keeps_the_servers_reason(cli):
    settings_file.set_project_model(cli.project, "public")
    cli.project = "00000000-0000-4000-8000-00000000abcd"
    with pytest.raises(ConnectionError) as refused:
        coding.routed_model(cli.issuer, cli.project, cli.token, {"public"}, print)
    assert str(refused.value) == "This project is unavailable."


def test_csw_07_an_ended_sign_in_is_reported_as_expired(cli):
    settings_file.set_project_model(cli.project, "public")
    cli.stores.identity.logout(cli.token)
    with pytest.raises(SignInExpired):
        coding.routed_model(cli.issuer, cli.project, cli.token, {"public"}, print)
