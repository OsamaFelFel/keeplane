# Self-hosting scenario map cases

**Edition:** Open Source. [`test_self_hosting_scenario_map.py`](test_self_hosting_scenario_map.py)
reads the "Spec 002 scenarios" table in the [Self-hosting cases](../e2e/self-hosting-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| SHM-01 | Read the table. | Every Spec 002 scenario, ST1 to ST5, is listed exactly once, by story and name, and nothing else. |
| SHM-02 | Read each scenario's "Checked by" cell. | A proven scenario names at least one case. A scenario on the test's not-proven list (ST2 "Runs where only the models are reachable", ST3 "A local model works like a cloud one") starts with "Not proven yet:", then says in words which run is missing before it names any case, then names the cases that come closest. The reason is written only in the table, not repeated in the test. A proven scenario never starts with "Not". |
| SHM-03 | Read the cases each proven scenario names. | At least one is a check CI runs on the current revision that does not only render the chart: not from the render catalogs (installation shape, network policy, chart package) and not from the live catalogs (K8S, FULL, EXEDGE, EXIST, GW-KEY), unless the case belongs to a test file on the `LIVE_TESTS` line of the Kubernetes live workflow (`.github/workflows/kubernetes-live.yml`) or the Kubernetes isolated network workflow (`.github/workflows/kubernetes-isolated.yml`), which run it on kind on every revision. The one exception, written in the test with its reason: for ST3 "The managed gateway always requires keys", Helm's install refusal cases SHAPE-08 and PKG-04 count, because a refusal under `helm template` is the refusal `helm install` gives (governance issue #47). |
| SHM-04 | Look up each case the table names, including those in not-proven cells. | Each has a row in its own catalog, the one the table's intro links for its prefix (SHAPE in the installation shape cases, EGR in the outbound connection cases, K8S in the local Kubernetes cases, and so on), and a test named after it, or its ID in a test's report or title. A row with the same ID in another catalog doesn't count, and a prefix with no known catalog fails. |
| SHM-05 | Read the table's intro. | It links every catalog the table's cases come from. |
| SHM-06 | Read the `LIVE_TESTS` lines of the Kubernetes live and isolated network workflows. | It names existing `tests/e2e` test files; their declared cases are those the workflow runs: the replica, customer-run gateway, preflight and gateway-down and copy-stop cases (K8S-01 to K8S-13, K8S-17 to K8S-21), and not the simulated preflight retries (K8S-14 to K8S-16), whose test file it does not run; and the isolated-network cases (ISO-01 to ISO-09). |
| SHM-07 | Read ST4 "One gateway copy stops" against its two clauses in Spec 002. | Its cell names K8S-03 for "new model calls are still answered" and K8S-18 for "a reply already streaming from that copy may fail visibly and can be retried", both cases come from a test file on the `LIVE_TESTS` line, and the cell no longer says a clause is not exercised. |

When Spec 002 adds or renames a scenario, update the list in the test and the
table together. When a not-proven scenario's missing run passes, take it off
the test's not-proven list and name the cases that ran. When the table names
cases from a new catalog, add the prefix and catalog to the test's list and
link the catalog in the intro.
