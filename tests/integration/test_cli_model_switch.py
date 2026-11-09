"""The CLI's `keeplane use` switch on the real task-model route (Spec 004 ST17).

Cases: tests/integration/cli-model-switch-cases.md (CSW-01 to CSW-04). The CLI's
own request code reaches the real Django runtime routes, accounts, policy and
enrollment files of the task routing cases through the test client: a
Confidential project with `private` (the developer's own key), `public` and
`outside`.
"""

from urllib.parse import urlencode

import pytest
from model_registry.models import ModelApproval

from components.cli import coding, server_connection, settings_file
from components.cli.server_connection import ConnectionError, SignInExpired
from tests.integration.test_model_choice import choice  # noqa: F401
from tests.integration.test_task_routing import rule, task  # noqa: F401

pytest_plugins = ("tests.integration.test_installed_personal_runtime",)
pytestmark = pytest.mark.django_db(transaction=True)

ISSUER = "http://127.0.0.1"


@pytest.fixture
def cli(task, monkeypatch, tmp_path):  # noqa: F811
    """The CLI's requests go to the real routes; its settings stay in tmp_path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    task.sent = []

    def bridge(
        server,
        path,
        credential,
        *,
        method="GET",
        expected=200,
        payload=None,
        query=None,
    ):
        task.sent.append((path, query))
        response = task.client.generic(
            method,
            path + ("?" + urlencode(query) if query else ""),
            HTTP_AUTHORIZATION="Bearer " + credential,
        )
        if response.status_code == 401:
            raise SignInExpired()
        if response.status_code != expected:
            raise ConnectionError(
                "The server refused this action.", response.status_code
            )
        return response.content

    monkeypatch.setattr(coding, "request", bridge)
    monkeypatch.setattr(server_connection, "request", bridge)
    return task


def allowed(f):
    return {
        row["id"]
        for row in server_connection.models(ISSUER, f.project, f.token)["models"]
    }


def test_csw_01_the_switch_beats_the_persona_rule_and_the_level(cli):
    rule(cli, "architect", "public")
    cli.stores.catalog.change_level("complex", "outside", {"outside"})
    # Without a switch the persona rule decides.
    picked = coding.task_model(
        ISSUER, cli.project, cli.token, persona="architect", level="complex"
    )
    assert (picked["model_id"], picked["chosen_by"]) == ("public", "persona_rule")
    # The CLI sends the switch as the route's model ID, and it wins.
    switched = coding.task_model(
        ISSUER, cli.project, cli.token, "private", persona="architect", level="complex"
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
        ISSUER, cli.project, cli.token, allowed(cli), notices.append
    )
    assert model == "public"
    assert notices == [coding.USING_SWITCH.format(model="public")]
    settings_file.set_project_model(cli.project, None)
    notices.clear()
    model = coding.routed_model(
        ISSUER, cli.project, cli.token, allowed(cli), notices.append
    )
    assert notices == [coding.USING_PICK.format(model=model)]


def test_csw_03_a_model_the_project_doesnt_allow_is_refused(cli):
    ModelApproval.objects.filter(pk="outside").update(approved_classes=["Public"])
    # `keeplane use` checks this list, so the switch can't be saved.
    assert "outside" not in allowed(cli)
    # A switch saved before the class changed is refused by the server too,
    # and no persona rule or level replaces it.
    rule(cli, "architect", "public")
    settings_file.set_project_model(cli.project, "outside")
    with pytest.raises(ConnectionError) as refused:
        coding.routed_model(ISSUER, cli.project, cli.token, {"outside"}, print)
    assert str(refused.value) == coding.SWITCH_NOT_ALLOWED.format(model="outside")
    with pytest.raises(ConnectionError) as refused:
        coding.routed_model(ISSUER, cli.project, cli.token, allowed(cli), print)
    assert str(refused.value) == coding.SWITCH_NOT_ALLOWED.format(model="outside")


def test_csw_04_without_a_usable_own_key_the_server_moves_the_switch(cli):
    rule(cli, "architect", "public")
    cli.store.remove("private")
    settings_file.set_project_model(cli.project, "private")
    notices = []
    model = coding.routed_model(
        ISSUER, cli.project, cli.token, allowed(cli), notices.append
    )
    assert model == "outside"  # The first allowed model: the CLI names no persona.
    assert notices == [
        (
            "No provider key is added for private; using outside instead. "
            "Add one with `keeplane keys set --model private`."
        )
    ]
    assert settings_file.project_model(cli.project) == "private"
