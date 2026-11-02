# Accounts scenario map cases

**Edition:** Open Source. [`test_accounts_scenario_map.py`](test_accounts_scenario_map.py)
reads the "Spec 003 scenarios" table in the [account and edition cases](../e2e/accounts-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| ACSM-01 | Read the table. | Every Spec 003 ST6, ST7, ST8 and ST28 scenario is listed exactly once, and nothing else. |
| ACSM-02 | Read each scenario's "Checked by" cell. | A built scenario names at least one case. A scenario that can't be proved yet starts "Not built yet:" followed by the reason; today that is only "Single sign-on connected", because no provider can be connected until Spec 011 is handed off. |
| ACSM-03 | Look up each case the table names, including any named beside a "Not built yet" reason. | Each has a row in its own catalog, the one the table's intro links for its prefix (LA in the account API cases, BSEC in the browser security cases, and so on), and a test named after it, or its ID in a test's report or title. A row with the same ID in another catalog doesn't count, and a prefix with no known catalog fails. |

When Spec 003 adds or renames a scenario, update the list in the test and the
table together. When a scenario becomes provable, remove it from the test's
not-built list and name its cases in the table. When the table names cases from
a new catalog, add the prefix and catalog to the test's list.
