"""Persona rules: an admin sends one persona's work to a chosen model.

Spec 004 ST15 (D28, D106). Each predefined persona (D24) has at most one rule.
Adding a rule for a persona that already has one moves it to the new model.
A rule only names a model that is set up in Keeplane now; a rule whose model
is no longer set up stays recorded but sends no work until it is set up again.
How a rule is applied to a task is in routing.py.
"""

from .models import Persona

PERSONAS = tuple((persona.value, persona.label) for persona in Persona)
PERSONA_NAMES = dict(PERSONAS)


class PersonaRuleError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def persona_rule_rows(rules, set_up_model_ids):
    """Describe each rule for Models and routing, in persona order."""
    set_up = set(set_up_model_ids)
    return [
        {
            "persona": persona,
            "name": name,
            "model_id": rules[persona],
            "model_set_up": rules[persona] in set_up,
        }
        for persona, name in PERSONAS
        if persona in rules
    ]


def persona_choices():
    return [{"persona": persona, "name": name} for persona, name in PERSONAS]


def describe_rule_change(persona, previous, chosen):
    """Say what an admin changed for one persona rule, for the settings record."""
    name = PERSONA_NAMES[persona]
    if previous is None:
        return f"Added persona rule {name}: route to model {chosen}"
    if chosen is None:
        return f"Removed persona rule {name}: it routed to model {previous}"
    return f"Changed persona rule {name}: model {previous} to model {chosen}"
