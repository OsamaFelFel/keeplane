# Developer CLI scenario map cases

**Edition:** Open Source. [`test_developer_cli_scenario_map.py`](test_developer_cli_scenario_map.py)
reads the "Spec 009 scenarios" table in the [Developer CLI cases](../e2e/developer-cli-cases.md).
Task 009-14.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| DCSM-01 | Read the table. | Every Spec 009 scenario, ST29 (5), ST30 (3) and ST31 (4), is listed exactly once, by story and name, and nothing else. |
| DCSM-02 | Read each scenario's "Proven by" and "Closest evidence" cells. | No closest-evidence cell is empty ("—" when there is nothing to add). A proven scenario names at least one case in "Proven by" and never starts with "Not". A scenario on the test's not-proven list (today ST30 "Cloud models use API keys") starts "Not proven yet:", says in words what is missing before it names any case, and names at least one case under closest evidence. The reason is written only in the table. |
| DCSM-03 | Look up where each case in a "Proven by" cell runs, including those in a not-proven cell. | Each runs in CI on the current revision: in the unit or integration shards (its own test file is in that shard and the test named after it isn't marked live or optional), or in a test file listed by the `cli-sign-in` or `coding-runtime` job of `checks.yml`, or the `live-gateway` job of `live-preview.yml`, each of which fails on a skipped case. A case CI doesn't run belongs under closest evidence. |
| DCSM-04 | Look up each case the table names, in either column. | Each has a row in its own catalog, the one the table's intro links for its prefix (NB in the no-browser cases, DU and DU-C in the developer usage cases, and so on; KEY-09 in the coding runtime cases, unlike KEY-01 to KEY-08), as a table row or a list item that starts with the case, and its own test file names it: a test named after it, or its ID in a test's report or title. A prefix with no known catalog fails. |
| DCSM-05 | Read the table's intro. | It links every catalog the table's cases come from. |
| DCSM-06 | Read each DEV case the table names. | It is in the developer journey suite's `CASES`, so a DEV case mentioned only in another file's comment doesn't count. Today the suite has DEV-01 to DEV-05 (and DEV-03b). |
| DCSM-07 | Point a case at a test marked live and optional as if the shards ran it, at a file no job lists, and at a catalog with no CI job. | None of them counts as run in CI. |

When Spec 009 adds or renames a scenario, update the list in the test and the
table together. When a not-proven scenario's missing check runs in CI, take it
off the test's not-proven list and name the cases. When the journey suite adds
DEV-06 to DEV-08, name them in the rows the table's intro gives. When the table
names cases from a new catalog, add the prefix, catalog, test file and CI job
to the test's list and link the catalog in the intro.
