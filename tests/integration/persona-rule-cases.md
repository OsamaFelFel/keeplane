# Persona rule cases

These cases cover Spec 004 ST15 (Add persona rule, the rule shows under Persona
rules), the ST23 removal guard for models a persona rule uses (D121) and the
Spec 006 ST21 settings-change record. Run
`.venv/bin/python -m pytest tests/integration/test_persona_rules.py`. They use
Django storage and the in-memory gateway of the
[complexity level cases](complexity-level-cases.md): three set-up models and
one gateway-only model. Whether a rule sends a task to its model is in the
[task routing cases](task-routing-cases.md).

| Case | Given | Expected result |
| --- | --- | --- |
| PR-INT-01 Add a rule | An admin opens Models and routing, then adds an Architect rule | There are no rules and three personas; afterwards the rule shows under Persona rules in the answer and on the next read. |
| PR-INT-02 Records | Settings changes are on. The admin adds the rule, adds it again, moves it, removes it twice | Three records name the admin and each change; unchanged requests add nothing. |
| PR-INT-03 Recording off | Settings changes are off | The rule is stored and no record is written. |
| PR-INT-04 Only set-up models | A gateway-only model, then a model whose definition changed | Refused with 400 “Choose a model that is set up”; nothing is stored. |
| PR-INT-05 Model no longer set up | A rule's model definition changes in the gateway | The rule stays recorded and is shown as not set up. |
| PR-INT-06 Guarded removal | Two rules and a level use one Keeplane-added model | Remove answers 409 listing Complex and Architect, Frontend; the gateway is not asked; nothing is recorded. Once the level and both rules move, removal works. |
| PR-INT-07 Outside model | A rule uses a model added outside Keeplane | Remove Keeplane setup is refused the same way. |
| PR-INT-08 Settings lock | A caller skips the early check, or chooses a model whose setup is already gone | The catalog still refuses removal without calling the gateway, and refuses the rule. |
| PR-INT-09 Refused requests | Unknown persona, a non-text model, extra fields, a JSON array, string or null body, a request without the admin-UI header, and a developer | 404, 400, 400, 400 “Enter a JSON object”, 403 and 403; nothing is stored or recorded. |
| PR-INT-10 Gateway or record fails | The gateway model list doesn't answer; the record write fails | The rule is refused with 503 and not stored. |

SC-14 and SC-15 in the [settings-change record cases](settings-change-record-cases.md)
run the rule records and the rule/removal race in separate processes on SQLite
and PostgreSQL. MR-22 and MR-23 in the [removal cases](../unit/model-removal-cases.md)
cover the guard without a database. The React and browser cases are PR-UI-01 to
PR-UI-07 in the [UI cases](../unit/ui/cases.md) and MO-UI-10 and MO-UI-11 in
the [browser Models cases](../browser/models-cases.md).
