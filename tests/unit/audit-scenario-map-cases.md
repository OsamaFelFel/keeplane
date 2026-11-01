# Audit scenario map cases

**Edition:** Open Source. [`test_audit_scenario_map.py`](test_audit_scenario_map.py)
reads the "Spec 006 scenarios" table in the [Audit cases](../e2e/audit-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| ASM-01 | Read the table. | Every Spec 006 ST21 and ST22 scenario is listed exactly once, and nothing else. |
| ASM-02 | Read each scenario's "Checked by" cell. | A built scenario names at least one case; "Held-back requests" says it is not built yet. |
| ASM-03 | Look up each case the table names. | Each has a row in a case catalog under `tests/` and a test named after it, or its ID in a test's report or title. |

When Spec 006 adds or renames a scenario, update the list in the test and the
table together. When held-back request records are built (after task 005-03),
replace "Not built yet" with their cases.
