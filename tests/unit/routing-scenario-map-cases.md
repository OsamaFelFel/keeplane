# Models and routing scenario map cases

**Edition:** Open Source. [`test_routing_scenario_map.py`](test_routing_scenario_map.py)
reads the "Spec 004 scenarios" table in the
[Models and routing cases](models-routing-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| RSM-01 | Read the table. | Every Spec 004 scenario, ST10 to ST17 and ST23 to ST27, is listed exactly once, and nothing else. |
| RSM-02 | Read each scenario's "Checked by" cell. | A built scenario names at least one case. A scenario on the test's not-built list (ST14 "Route by complexity", ST17 "See the model", "Switch the model" and "My switch beats Keeplane's picks") starts with "Not built yet:" and says why; a built one never does. |
| RSM-03 | Look up each case the table names, including any a not-built cell mentions. | Each has a row in its own catalog, the one the table's intro links for its prefix (MRS in the Models and routing cases, MC in the model choice cases, and so on), as a table row or a list item that starts with the case, and a test named after it, or its ID in a test's report or title. A row with the same ID in another catalog doesn't count, and a prefix with no known catalog fails. |

When Spec 004 adds or renames a scenario, update the list in the test and the
table together. When a not-built scenario is built, take it off the test's
not-built list and name its cases. When the table names cases from a new
catalog, add the prefix and catalog to the test's list.
