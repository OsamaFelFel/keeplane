"""Spec 004 ST15 and ST17: which allowed model a task goes to, and why.

Precedence inside what the project allows (D150): the developer's switch, then
the persona rule, then the complexity level, then the first allowed model. The
plain-English cases are in task-routing-cases.md.
"""

import pytest
from model_registry import routing
from model_registry.levels import ModelInUse
from model_registry.models import ModelApproval

from tests.integration.test_installed_personal_runtime import KEY
from tests.integration.test_model_choice import choice  # noqa: F401

pytest_plugins = ("tests.integration.test_installed_personal_runtime",)
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def task(choice, monkeypatch):  # noqa: F811
    monkeypatch.setattr(routing, "CATALOG", choice.stores.catalog)
    choice.install("public")
    choice.install("outside")
    return choice


def ask(f, token=None, **query):
    return f.client.get(
        f"/api/runtime/projects/{f.project}/task-model",
        query,
        HTTP_AUTHORIZATION="Bearer " + (token or f.token),
    )


def routed(f, **query):
    response = ask(f, **query)
    assert response.status_code == 200, response.content
    body = response.json()
    return body["model_id"], body["chosen_by"]


def rule(f, persona, model_id):
    f.stores.catalog.set_persona_rule(persona, model_id, {model_id})


def test_rt_01_the_persona_rule_applies(task):
    rule(task, "architect", "public")
    response = ask(task, persona="architect")
    assert response.json() == {
        "project_id": task.project,
        "requested_model_id": None,
        "persona": "architect",
        "level": None,
        "model_id": "public",
        "chosen_by": "persona_rule",
        "reason": None,
    }
    assert "no-store" in response["Cache-Control"]
    # Another persona has no rule, so its task goes elsewhere.
    assert routed(task, persona="frontend") == ("outside", "first_allowed")


def test_rt_02_my_switch_beats_the_persona_rule_and_the_level(task):
    rule(task, "architect", "public")
    task.stores.catalog.change_level("complex", "outside", {"outside"})
    assert routed(task, persona="architect", level="complex") == (
        "public",
        "persona_rule",
    )
    assert routed(task, model_id="private", persona="architect", level="complex") == (
        "private",
        "developer",
    )
    assert routed(task, model_id="outside", persona="architect") == (
        "outside",
        "developer",
    )


def test_rt_03_the_persona_rule_beats_the_level(task):
    task.stores.catalog.change_level("complex", "outside", {"outside"})
    assert routed(task, level="complex") == ("outside", "complexity_level")
    rule(task, "frontend", "private")
    assert routed(task, persona="frontend", level="complex") == (
        "private",
        "persona_rule",
    )


def test_rt_04_keeplanes_level_pick_is_made_from_the_projects_models(task):
    # No context windows are known, so model ID decides: outside, private, public.
    assert routed(task, level="simple") == ("outside", "complexity_level")
    assert routed(task, level="standard") == ("private", "complexity_level")
    assert routed(task, level="complex") == ("public", "complexity_level")
    # An admin's pick that the project's class doesn't allow gives way to
    # Keeplane's pick among the models the project may use.
    task.stores.catalog.change_level("complex", "outside", {"outside"})
    ModelApproval.objects.filter(pk="outside").update(approved_classes=["Public"])
    assert routed(task, level="complex") == ("public", "complexity_level")


def test_rt_05_a_rule_for_a_model_the_project_cant_use_gives_way(task):
    rule(task, "architect", "outside")
    ModelApproval.objects.filter(pk="outside").update(approved_classes=["Public"])
    assert routed(task, persona="architect", level="complex") == (
        "public",
        "complexity_level",
    )
    body = ask(task, persona="architect").content.decode()
    assert "outside" not in body


def test_rt_06_a_rule_never_reaches_a_gateway_only_or_unusable_model(task):
    rule(task, "architect", "outside")
    # Its definition changes in the gateway outside Keeplane, so the setup no
    # longer matches: the model is present in the gateway only.
    changed = next(item for item in task.resources if item["id"] == "outside")
    changed["revision"] += 1
    assert routed(task, persona="architect") == ("private", "first_allowed")
    # A removed setup can't leave a rule behind: the rule keeps the model.
    with pytest.raises(ModelInUse):
        task.stores.catalog.remove("outside")
    # A rule on a Personal model is skipped while the developer's own key is
    # missing, and applies again once it is back.
    rule(task, "architect", "private")
    task.store.remove("private")
    assert routed(task, persona="architect") == ("public", "first_allowed")
    task.store.put("private", KEY)
    assert routed(task, persona="architect") == ("private", "persona_rule")


def test_rt_07_a_switch_to_a_model_the_project_cant_use_is_refused(task):
    rule(task, "architect", "public")
    ModelApproval.objects.filter(pk="outside").update(approved_classes=["Public"])
    response = ask(task, model_id="outside", persona="architect")
    assert response.status_code == 403
    assert response.json() == {"error": "This model is not eligible for the project"}
    response = ask(task, model_id="gateway-only-model", persona="architect")
    assert response.status_code == 403


def test_rt_08_a_switch_without_a_usable_own_key_follows_the_order(task):
    rule(task, "architect", "public")
    task.store.remove("private")
    response = ask(task, model_id="private", persona="architect")
    assert response.json() == {
        "project_id": task.project,
        "requested_model_id": "private",
        "persona": "architect",
        "level": None,
        "model_id": "public",
        "chosen_by": "persona_rule",
        "reason": "missing",
    }
    # With no persona or level the next model is the first allowed one.
    assert routed(task, model_id="private") == ("outside", "first_allowed")


def test_rt_09_nothing_allowed_gives_no_model(choice, monkeypatch):  # noqa: F811
    monkeypatch.setattr(routing, "CATALOG", choice.stores.catalog)
    rule(choice, "architect", "private")
    choice.store.remove("private")
    assert routed(choice, persona="architect") == (None, None)


@pytest.mark.parametrize(
    "query",
    [
        {"persona": "tester"},
        {"level": "expert"},
        {"model_id": ""},
        {"owner_id": "forged"},
        {"persona": ["architect", "frontend"]},
    ],
)
def test_rt_10_invalid_requests_are_refused(task, query):
    response = ask(task, **query)
    assert response.status_code == 400
    assert response.json() == {"error": "Send at most one model ID, persona and level"}


def test_rt_11_signed_out_unknown_project_and_policy_outage(task):
    assert ask(task, token="invalid", persona="architect").status_code == 401
    task.state.status = 503
    response = ask(task, persona="architect")
    assert response.status_code == 503
    assert response.json() == {"error": "Model routing is unavailable"}
    task.state.status = 200
    project = task.project
    task.project = "00000000-0000-4000-8000-00000000abcd"
    assert ask(task, persona="architect").status_code == 403
    task.project = "not-a-project"
    assert ask(task, persona="architect").status_code == 403
    task.project = project


def test_rt_12_a_project_the_access_policy_refuses_gets_no_model(task, monkeypatch):
    from model_registry import model_choice

    rule(task, "architect", "public")
    monkeypatch.setattr(
        model_choice,
        "organization_project_access",
        lambda actor_id, project_id: project_id != task.project,
    )
    response = ask(task, persona="architect")
    assert response.status_code == 403
    assert "public" not in response.content.decode()


def test_rt_13_response_contains_no_key_material(task):
    rule(task, "architect", "private")
    body = ask(task, persona="architect").content.decode()
    for secret in (KEY, task.fp, task.token, str(task.key_directory)):
        assert secret not in body


def test_rt_14_the_gateway_still_admits_the_routed_model(task):
    from tests.integration.test_installed_runtime import send as entry

    rule(task, "architect", "public")
    model_id, _ = routed(task, persona="architect")
    assert model_id == "public"
    assert entry(task, model_id=model_id).status_code == 200
