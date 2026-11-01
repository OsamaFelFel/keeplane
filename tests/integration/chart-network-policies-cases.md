# Chart network policy cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_network_policies.py`
with Helm 3.19 or newer. The checks find Helm through `KEEPLANE_HELM_BIN`, else
`helm` on `PATH`; without Helm they are skipped, and a skipped case is not a pass.

Each case renders the chart with `helm template`: the PostgreSQL installation
with the managed gateway, the same installation with an existing (customer-run)
gateway, and the managed local trial in `deploy/local/values.yaml`. The
PostgreSQL values are the ones the [installation shape cases](chart-installation-shape-cases.md)
use. The policies are described in the
[Kubernetes installation reference](../../docs/guide/kubernetes-installation-reference.md#network-policies).

Rendering proves which NetworkPolicies the chart asks Kubernetes to create and
which pods they select. It does not prove that a cluster enforces them: that
needs a network plugin that enforces NetworkPolicy and a live trial, which these
cases do not run.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| NETPOL-01 | Render the managed and existing PostgreSQL installations and the local trial with default policy settings. Then give a misspelled setting, an address range that is a host name, a destination without ports, a port given as text or above 65535, a non-text label value, and an unknown destination field. | No NetworkPolicy renders by default in any of them. Helm's values check refuses every invalid setting before installation. |
| NETPOL-02 | Turn on app ingress with the ingress controller's namespace and pod labels, in managed and existing mode; then with pod labels only. | One policy selects only the app pods (not the gateway copies or Jobs) and admits only pods matching the given labels, on TCP 3000. It has no address range. With pod labels only, the rule stays inside the release namespace. |
| NETPOL-03 | Turn on app ingress without any public entry labels; with a NodePort app Service; and in the local trial, which publishes the app on a NodePort. | Helm refuses each one. The messages name `networkPolicy.publicEntry` or require `app.service.type=ClusterIP`. |
| NETPOL-04 | Turn on egress in the managed PostgreSQL installation with model endpoints, database addresses and runners, then without runners. | The app's egress policy selects only the app pods and allows exactly: cluster DNS on UDP and TCP 53; this release's gateway copies on TCP 4000; the listed PostgreSQL address; the listed model endpoints, which the app's provider-key checks call; and the listed runners. Without runners there is no runner rule. Nothing else is allowed. |
| NETPOL-05 | In the same installation, read the gateway copies' egress policy. | It selects the gateway copies and the bundled zero-replica Deployment, and allows exactly DNS, the listed gateway database and the listed model endpoints. The app is not a destination: the copies never call it in this chart. |
| NETPOL-06 | Read the migration Job's egress policy; then turn off the chart's migration Job. | It selects only the migration Job's pods and allows exactly DNS and the listed PostgreSQL address. It is an install and upgrade hook with a lower weight than the Job, so it exists before the Job starts. With external migrations there is no Job and no Job policy. |
| NETPOL-07 | Turn on egress in existing-gateway mode, with the supplied gateway given by namespace and pod labels and then by address range. Then try the gateway ingress policy and a gateway database list in existing mode. | Only Keeplane pods get policies: the app reaches DNS, the supplied gateway, PostgreSQL and the model endpoints; the preflight Job (a hook) reaches DNS and the supplied gateway only. No gateway object or gateway policy renders. Helm refuses both gateway settings and says they belong to managed mode. |
| NETPOL-08 | Turn on egress without model endpoints (both modes), without the app database, without the gateway database, or in existing mode without the supplied gateway. Also list the supplied gateway in managed mode, an entry with both an address range and labels, an entry with an empty selector, a cleared DNS setting, a gateway database with a read-only gateway, and a PostgreSQL list in the local trial. | Helm refuses every one before installation and names the missing or contradictory setting. |
| NETPOL-09 | Turn on egress in the local trial (SQLite), and with a read-only managed gateway; then give DNS as an address range. | The local trial's app reaches DNS, the gateway copies and the model endpoints, with no PostgreSQL rule and no Job policy. A read-only gateway gets no database rule and needs no database list. A DNS address range replaces the DNS labels. |
| NETPOL-10 | Turn every policy on in both modes and match each policy's pod selector against every workload's pod labels. | Every Deployment, StatefulSet and Job pod is selected by an egress policy, so no Keeplane pod is left unrestricted. No rule has an empty peer, an empty label selector or no ports. |

Not covered here: enforcement on a live cluster, model endpoints that change
address (NetworkPolicy cannot match host names), and who may set the trusted
app pod label.
