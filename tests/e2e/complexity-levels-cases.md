# Live complexity level cases

Run against the protected Docker or kind preview:

```sh
.venv/bin/python -m pytest tests/e2e/test_complexity_levels.py -m live
```

The check adds its own fixture model, restores the Complex level and the
settings-change Audit switch, and removes the model afterwards. Rule-level
cases are in the [integration complexity level cases](../integration/complexity-level-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| LEVEL-LIVE-01 | Add a fixture model through Keeplane, then open Models and routing. | Simple, Standard and Complex each have a model. |
| LEVEL-LIVE-02 | With settings changes on, change Complex to that model. | Complex shows it as changed by an admin and Audit has a settings record by first-admin ending “to model [name]”. |
| LEVEL-LIVE-03 | Remove that model. | 409 lists Complex; the model stays listed. |
| LEVEL-LIVE-04 | Put Complex back as it was, then remove the model. | The removal succeeds. |
