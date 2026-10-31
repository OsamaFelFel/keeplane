# Persona rule unit cases

Spec 004 ST15 and ST17 (D28, D106, D150). Run
`.venv/bin/python -m pytest tests/unit/test_persona_rules.py`. The routing
cases PR-05 to PR-09 use an in-memory stand-in for the shared fallback filter;
the [task routing cases](../integration/task-routing-cases.md) run the same
order against real accounts, policy and keys.

| Case | Given | Expected result |
| --- | --- | --- |
| PR-01 Personas | The persona list | Architect, Developer and Frontend, in that order, offered as Add rule choices. |
| PR-02 Rows | Rules for Frontend and Architect, one on a model that isn't set up now | Listed Architect first, each with its model and whether that model is set up. No rules gives an empty list. |
| PR-03 Record wording | Adding, moving and removing a rule | `Added a persona rule for Architect: large`, `Changed the persona rule for Architect to small`, `Removed the persona rule for Frontend`. |
| PR-04 In-use answer | A model a level and a persona rule use | The answer lists both. |
| PR-05 Order | Three allowed models; an Architect rule; a level | The developer's switch wins, then the persona rule, then the level's model, then the first allowed model. |
| PR-06 Rule gives way | The rule's model isn't allowed for the project's class, or the runtime gate refuses it now | The level's model, or the first allowed model, is used instead. |
| PR-07 Level inside the project | An admin chose the largest model for Simple | It is used while the project allows it; otherwise Keeplane's pick among the project's models. |
| PR-08 Switch without a usable own key | The developer switched to a model whose own key is missing | The task follows the same order without that model and keeps the reason; a rule naming that model is skipped. |
| PR-09 Nothing allowed | No model is allowed | No model and no deciding step. |
