"""Persona rules as Models and routing shows them, and the routing order.

Spec 004 ST15 and ST17 (D28, D106, D150). The plain-English cases are in
persona-rule-cases.md.
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "components/control-plane")
)

from model_registry.levels import ModelInUse
from model_registry.persona_rules import (
    PERSONAS,
    describe_rule_change,
    persona_choices,
    persona_rule_rows,
)
from model_registry.routing import TaskRouting


def test_pr_01_the_predefined_personas_in_order():
    assert PERSONAS == (
        ("architect", "Architect"),
        ("developer", "Developer"),
        ("frontend", "Frontend"),
    )
    assert persona_choices() == [
        {"persona": "architect", "name": "Architect"},
        {"persona": "developer", "name": "Developer"},
        {"persona": "frontend", "name": "Frontend"},
    ]


def test_pr_02_rules_are_listed_in_persona_order_with_their_setup():
    rows = persona_rule_rows({"frontend": "small", "architect": "gone"}, ["small"])
    assert rows == [
        {"persona": "architect", "name": "Architect", "model_id": "gone", "model_set_up": False},
        {"persona": "frontend", "name": "Frontend", "model_id": "small", "model_set_up": True},
    ]
    assert persona_rule_rows({}, ["small"]) == []


def test_pr_03_record_wording():
    assert (
        describe_rule_change("architect", None, "large")
        == "Added persona rule Architect: route to model large"
    )
    assert (
        describe_rule_change("architect", "large", "small")
        == "Changed persona rule Architect: model large to model small"
    )
    assert (
        describe_rule_change("frontend", "small", None)
        == "Removed persona rule Frontend: it routed to model small"
    )


def test_pr_04_in_use_answer_lists_levels_and_persona_rules():
    assert ModelInUse("m", ["Complex"], ["Architect"]).body() == {
        "error": "m is still in use. Move these to another model first, then remove it.",
        "in_use": {"levels": ["Complex"], "persona_rules": ["Architect"]},
    }


class Choice:
    """The one fallback filter, with every allowed model usable unless listed."""

    def __init__(self, eligible, unusable=(), switch_reason=None):
        self.eligible, self.unusable = set(eligible), set(unusable)
        self.switch_reason = switch_reason
        self.policy = self
        self.authorization = self

    def eligible_model_ids(self, project_id):
        return frozenset(self.eligible)

    def _usable(self, owner_id, model_id):
        return model_id not in self.unusable

    def authorize(self, token, project_id, model_id):
        return {"actor_id": "dev", "project_id": project_id, "model_id": model_id}

    def choose(self, token, project_id, model_id):
        reason = self.switch_reason
        moved = self.next_allowed(token, "dev", project_id, skip={model_id})
        return {
            "project_id": project_id,
            "requested_model_id": model_id,
            "model_id": model_id if reason is None else moved,
            "reason": reason,
        }

    def next_allowed(self, token, owner_id, project_id, *, skip):
        for candidate in sorted(self.eligible - set(skip) - self.unusable):
            return candidate
        return None


class Catalog:
    def __init__(self, rules=None, choices=None):
        self.rules, self.choices = rules or {}, choices or {}

    def persona_rules(self):
        return dict(self.rules)

    def level_choices(self):
        return dict(self.choices)

    def context_windows(self, model_ids):
        sizes = {"a-small": 4096, "b-medium": 32768, "c-large": 131072}
        return {model_id: sizes.get(model_id) for model_id in model_ids}


def route(choice, catalog, **query):
    routing = TaskRouting(choice, catalog)
    routing._actor = lambda token, project_id: ("dev", project_id)
    result = routing.route("token", "project", **query)
    return result["model_id"], result["chosen_by"]


ALL = ("a-small", "b-medium", "c-large")


def test_pr_05_precedence_switch_then_rule_then_level_then_first_allowed():
    catalog = Catalog(rules={"architect": "b-medium"})
    choice = Choice(ALL)
    assert route(choice, catalog, model_id="a-small", persona="architect", level="complex") == (
        "a-small",
        "developer",
    )
    assert route(choice, catalog, persona="architect", level="complex") == (
        "b-medium",
        "persona_rule",
    )
    assert route(choice, catalog, persona="frontend", level="complex") == (
        "c-large",
        "complexity_level",
    )
    assert route(choice, catalog, persona="frontend") == ("a-small", "first_allowed")
    assert route(choice, catalog) == ("a-small", "first_allowed")


def test_pr_06_a_rule_outside_the_project_or_unusable_gives_way():
    catalog = Catalog(rules={"architect": "c-large"})
    # The rule's model isn't allowed for this project's class.
    assert route(Choice(("a-small", "b-medium")), catalog, persona="architect", level="complex") == (
        "b-medium",
        "complexity_level",
    )
    # The rule's model is allowed but the runtime gate refuses it now.
    assert route(Choice(ALL, unusable={"c-large"}), catalog, persona="architect") == (
        "a-small",
        "first_allowed",
    )


def test_pr_07_an_admins_level_pick_wins_only_while_the_project_allows_it():
    catalog = Catalog(choices={"simple": "c-large"})
    assert route(Choice(ALL), catalog, level="simple") == ("c-large", "complexity_level")
    assert route(Choice(("a-small", "b-medium")), catalog, level="simple") == (
        "a-small",
        "complexity_level",
    )


def test_pr_08_a_switch_with_an_unusable_own_key_follows_the_same_order():
    catalog = Catalog(rules={"architect": "c-large"})
    choice = Choice(ALL, switch_reason="missing")
    routing = TaskRouting(choice, catalog)
    routing._actor = lambda token, project_id: ("dev", project_id)
    result = routing.route("token", "project", model_id="a-small", persona="architect")
    assert (result["model_id"], result["chosen_by"], result["reason"]) == (
        "c-large",
        "persona_rule",
        "missing",
    )
    # The rule never sends the task back to the model the developer can't use.
    catalog.rules["architect"] = "a-small"
    result = routing.route("token", "project", model_id="a-small", persona="architect")
    assert (result["model_id"], result["chosen_by"]) == ("b-medium", "first_allowed")


def test_pr_09_nothing_allowed_gives_no_model():
    assert route(Choice(()), Catalog(rules={"architect": "a-small"}), persona="architect") == (
        None,
        None,
    )
