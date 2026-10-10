# Current gateway bypass probes

**Edition:** Both. These are diagnostic cases against the local integration
gateway. A probe that captures a bypass succeeds as a diagnostic run but fails
the release policy contract. It does not select a release gateway.

| ID | Plain-English action | Release expectation |
| --- | --- | --- |
| GW-PROBE-01 | From a disposable Docker sibling and fresh kind pods with no Keeplane credential, ask the managed and supplied gateways for their runtime model list. | No model names are returned without a verified workload and developer identity. |
| GW-PROBE-02 | From those same sibling workloads, read the model-management API. | Management is unavailable to the sibling workload. |
| GW-PROBE-03 | Call the fixture model directly from the sibling workload, then compare the fixture's call counter before and after. | The gateway refuses the call; the upstream counter stays unchanged. |
| GW-PROBE-04 | Repeat the direct call with an invalid bearer and forged user, role, project and class headers. | Forged client fields do not authorize a call or reach the upstream. |
| GW-PROBE-05 | Try the corresponding public Keeplane model list, management and chat routes without a session. | The public edge refuses all three. |

Run `python3 tests/e2e/test_gateway_bypass_probe.py --output <new JSON path>`
from the repository root. The script checks the isolated `kind-keeplane`
context, uses no project or provider credential, and deletes its two test pods
in a `finally` block. Its output records only statuses and fixture call counts,
not prompts or credentials. GW-17–GW-23 in governance remain the actual release
acceptance cases; these probes expose the current setup's gaps.
Use `--targets docker` to check only the running Docker preview during a staged
rollout. `tested_probe_passes` covers only the paths in this table;
`release_gateway_selected` remains false even if every probe passes.
