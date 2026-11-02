# Self-hosting scenario map cases

**Edition:** Open Source. [`test_self_hosting_scenario_map.py`](test_self_hosting_scenario_map.py)
reads the "Spec 002 scenarios" table in the [Self-hosting cases](../e2e/self-hosting-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| SHM-01 | Read the table. | Every Spec 002 scenario, ST1 to ST5, is listed exactly once, by story and name, and nothing else. |
| SHM-02 | Read each scenario's "Checked by" cell. | A proven scenario names at least one case. A scenario on the test's not-proven list (ST1 "Install on the isolated network", ST2 "The install may pull from the registry" and "Runs where only the models are reachable", ST3 "A local model works like a cloud one", ST4 "One gateway copy stops", ST5 "We already run the gateway") starts with "Not proven yet:", says which run is missing, and names the cases that come closest; a proven one never starts with "Not". |
| SHM-03 | Read the cases each proven scenario names. | At least one comes from outside the chart render catalogs (installation shape, network policy, chart package), so no scenario counts as proven by `helm template` alone. |
| SHM-04 | Look up each case the table names, including those in not-proven cells. | Each has a row in its own catalog, the one the table's intro links for its prefix (SHAPE in the installation shape cases, EGR in the outbound connection cases, K8S in the local Kubernetes cases, and so on), and a test named after it, or its ID in a test's report or title. A row with the same ID in another catalog doesn't count, and a prefix with no known catalog fails. |
| SHM-05 | Read the table's intro. | It links every catalog the table's cases come from. |

When Spec 002 adds or renames a scenario, update the list in the test and the
table together. When a not-proven scenario's missing run passes, take it off
the test's not-proven list and name the cases that ran. When the table names
cases from a new catalog, add the prefix and catalog to the test's list and
link the catalog in the intro.
