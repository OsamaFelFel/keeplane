# Data class scenario map cases

**Edition:** Open Source. [`test_data_class_scenario_map.py`](test_data_class_scenario_map.py)
reads the "Spec 005 scenarios" table in the [Data classes cases](../e2e/data-classes-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| DSM-01 | Read the table. | Every Spec 005 ST18, ST19 and ST20 scenario is listed exactly once, by story and name, and nothing else. The two "Off by default" scenarios are told apart by their story. |
| DSM-02 | Read each scenario's "Checked by" cell. | Every scenario is built and names at least one case. A scenario in the test's not-built list would need a reason there and a cell starting "Not built yet"; none is listed now. |
| DSM-03 | Look up each case the table names. | Each has a row in its own catalog, one the table's intro links for its prefix (DCA in the data class admin cases, PR in the detection routing cases, DC-UI in the browser or React UI cases, and so on), and a test named after it, or its ID in a test's report, title or opening comment. A row with the same ID in another catalog doesn't count, and a prefix with no known catalog fails. |
| DSM-04 | Read the table's intro paragraph. | It links every catalog the table's cases come from. |

When Spec 005 adds or renames a scenario, update the list in the test and the
table together. When the table names cases from a new catalog, add the prefix
and catalog to the test's list and link the catalog in the intro.
