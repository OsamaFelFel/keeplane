# Live persona rule cases

Run against the protected Docker or kind preview:

```sh
.venv/bin/python -m pytest tests/e2e/test_persona_rules.py -m live
```

The check adds its own fixture model, puts the Architect rule back as it was
and restores the settings-change Audit switch, and removes the model
afterwards. Rule-level cases are in the
[integration persona rule cases](../integration/persona-rule-cases.md) and the
[task routing cases](../integration/task-routing-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| RULE-LIVE-01 | With settings changes on, add a fixture model and an Architect rule for it. | The rule shows under Persona rules and Audit has a settings record by first-admin for it. |
| RULE-LIVE-02 | Remove that model. | 409 lists the Architect rule; the model stays. |
| RULE-LIVE-03 | Put the Architect rule back as it was, then remove the model. | The removal succeeds. |
