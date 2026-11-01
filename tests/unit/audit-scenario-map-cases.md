# Audit scenario map cases

**Edition:** Open Source. [`test_audit_scenario_map.py`](test_audit_scenario_map.py)
reads the "Spec 006 scenarios" table in the [Audit cases](../e2e/audit-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| ASM-01 | Read the table. | Every Spec 006 ST21 and ST22 scenario is listed exactly once, and nothing else. |
| ASM-02 | Read each scenario's "Checked by" cell. | A built scenario names at least one case; "Held-back requests" says it is not built yet. |
| ASM-03 | Look up each case the table names. | Each has a row in its own catalog, the one the table's intro links for its prefix (MA in the model answer cases, BG in the Audit cases, and so on), and a test named after it, or its ID in a test's report or title. A row with the same ID in another catalog doesn't count, and a prefix with no known catalog fails. |

When Spec 006 adds or renames a scenario, update the list in the test and the
table together. When the table names cases from a new catalog, add the prefix
and catalog to the test's list. When held-back request records are built (after task 005-03),
replace "Not built yet" with their cases.
