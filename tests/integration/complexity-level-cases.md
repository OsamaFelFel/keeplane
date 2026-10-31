# Complexity level cases

These cases cover Spec 004 ST13 (Keeplane's picks, Change a level, Use
Keeplane's pick), the ST23 removal guard for admin-changed levels (D121) and
the Spec 006 ST21 settings-change record for "a complexity pick". The owner's
decision for this release sets three levels, Simple, Standard and Complex, and
Keeplane's pick by context window. Judging a task's complexity (ST14) is not
built. Persona rules (ST15) and the order that sends a task to the developer's
switch, a persona rule or a level's model (ST17) are in the
[persona rule cases](persona-rule-cases.md) and the
[task routing cases](task-routing-cases.md).

## Picks (unit)

Run `.venv/bin/python -m pytest tests/unit/test_complexity_levels.py`.

| Case | Given | Expected result |
| --- | --- | --- |
| CL-01 Levels | The level list | Simple, Standard and Complex, in that order. |
| CL-02 No model | No model is set up | Every level has no pick. |
| CL-03 Ranking | Models with 4,096, 32,768 and 131,072 tokens | Simple gets the smallest, Standard the middle and Complex the largest. |
| CL-04 One model | One set-up model | Every level picks it. |
| CL-05 Two models | Two set-up models | Simple and Standard pick the smaller, Complex the larger. |
| CL-06 Even count | Four set-up models | Standard picks the lower of the two middle models. |
| CL-07 Ties | Three models with the same context window, in any order | They are ranked by model ID: Simple first, Complex last. |
| CL-08 Unknown context | Two cloud models with no known context and one local model | The cloud models rank below the local one, by model ID. |
| CL-09 Admin change | An admin chose a model for Complex | Complex shows that model, marked as changed by an admin, and still names Keeplane's pick. Other levels stay on Keeplane's pick. |
| CL-10 Admin model not set up | An admin's model is no longer set up | The level shows Keeplane's pick and says the admin's model isn't set up; the choice stays recorded. |
| CL-11 Record wording | Changes to, between and away from an admin's model | `Changed complexity pick Complex: Keeplane's pick to model large`, `… model a to model b`, `… model a to Keeplane's pick`. |
| CL-12 In-use answer | A model used by an admin-changed level | The answer lists the levels and an empty persona-rule list. |

## Storage, API and removal (integration)

Run `.venv/bin/python -m pytest tests/integration/test_complexity_levels.py`.
These use Django storage and an in-memory gateway with three set-up models
(4,096, 32,768 and 131,072 tokens) and one gateway-only model.

| Case | Given | Expected result |
| --- | --- | --- |
| CL-INT-01 Keeplane's picks | An admin opens Models and routing | Each level shows Keeplane's pick: small, medium and large. |
| CL-INT-02 Only set-up models | The gateway lists a model that isn't set up, then a set-up model's definition changes | Neither is picked or accepted as an admin's choice (400); nothing is stored. |
| CL-INT-03 Change and go back | Settings changes are on. The admin changes Complex, saves it unchanged, changes it again and chooses Use Keeplane's pick twice | The level follows each change; three records name the admin and each change; unchanged requests add nothing. |
| CL-INT-04 Recording off | Settings changes are off | The change is stored and no record is written. |
| CL-INT-05 Picks follow models | An admin changed Simple; two models are added, then one on Keeplane's pick is removed | Keeplane's picks move with the models; Simple keeps the admin's model; removing a model on Keeplane's pick is allowed. Editing a model keeps its context window. |
| CL-INT-06 Guarded removal | Two levels were changed to one Keeplane-added model | Remove answers 409 listing Simple and Complex; the gateway is not asked; nothing is recorded. After the levels move, removal works. |
| CL-INT-07 Outside model | An admin-changed level uses a model added outside Keeplane | Remove Keeplane setup is refused the same way. |
| CL-INT-08 Settings lock | A caller skips the early check, or chooses a model whose setup is already gone | The catalog still refuses removal without calling the gateway, and refuses the level change. |
| CL-INT-09 Refused requests | Unknown level, a non-text model, extra fields, a JSON array, string or null body, a request without the admin-UI header, and a developer | 404, 400, 400, 400 "Enter a JSON object", 403 and 403; nothing is stored or recorded. |
| CL-INT-10 Record or storage fails | The settings record write fails; reading level choices fails | The change reports storage as unavailable and is not stored; Models answers 503. |
| CL-INT-11 Gateway down | The gateway model list doesn't answer | The change is refused and nothing is stored. |
| CL-INT-12 Runner context | A model is added from a runner that reports 16,384 tokens of active context | The approval records 16,384; an unknown model has no context window. |
| CL-INT-13 Invalid context | A zero, negative, text, fractional or true context value | The approval is refused and not stored. |

SC-12 and SC-13 in the [settings-change record cases](settings-change-record-cases.md)
run the level-change record and the change/remove race in separate processes
on SQLite and PostgreSQL.

The removal guard's transaction edges without a database are MR-20 and MR-21 in
the [removal cases](../unit/model-removal-cases.md). The React and browser
cases are CL-UI-01 to CL-UI-08 in the [UI cases](../unit/ui/cases.md) and
MO-UI-08 and MO-UI-09 in the [browser Models cases](../browser/models-cases.md).
