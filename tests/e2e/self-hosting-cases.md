# Self-hosting cases

**Edition:** Open Source. **Spec:** 002 Self-hosting (ADRs 007 to 011).

This page holds no checks of its own. It names, for each Spec 002 scenario, the
cases elsewhere that prove it, and says plainly which scenarios are not proven
yet and what run is still missing.

## Spec 002 scenarios (ST1–ST5)

Each scenario in Spec 002 and the cases that prove it. Each case is in its own
catalog:

- Chart render checks: SHAPE the
  [installation shape cases](../integration/chart-installation-shape-cases.md),
  NETPOL the [network policy cases](../integration/chart-network-policies-cases.md)
  and PKG the [chart package cases](../integration/chart-package-cases.md).
- Outbound connections: EGR the
  [outbound connection cases](../unit/outbound-connection-cases.md).
- Web UI assets: OFF the [built UI asset cases](../unit/ui-offline-assets-cases.md)
  and OFF-UI the [browser asset cases](../browser/offline-assets-cases.md).
- The pinned gateway image: GW-KEY the
  [gateway key cases](../integration/gateway-policy-cases.md).
- Live cluster and Docker trials: K8S the [local Kubernetes cases](kubernetes-cases.md),
  FULL the [full chart cases](full-product-edge-cases.md), EXEDGE the
  [customer-run gateway edge cases](full-existing-edge-cases.md) and EXIST the
  [customer-run gateway trial cases](existing-gateway-cases.md).

A render check runs `helm template`. When Helm refuses values there, `helm install`
refuses the same values, because both evaluate the templates before anything
reaches the cluster. Any other render result shows what the chart asks Kubernetes
to create, not what a cluster does with it, so a render check alone never proves
a live install here. A scenario counts as proven only by checks that run on the
current revision in CI, and never by render checks alone; the one exception is
Helm's install refusal for the managed gateway's keys, which is the refusal itself.
The **Kubernetes live checks** workflow (`.github/workflows/kubernetes-live.yml`)
installs the chart on a kind cluster on every revision and runs the test files on
its `LIVE_TESTS` line; their K8S cases (K8S-01 to K8S-13 and K8S-17) count as CI
checks. That cluster can reach the internet, has no ingress controller and does
not enforce NetworkPolicy. The other K8S cases, FULL, EXEDGE, EXIST and GW-KEY
are not run in CI. The live trials ran on a local kind cluster or Docker with
outside access, not on an isolated network, and a trial recorded on an earlier
chart revision is named as the closest evidence, not as proof.

`tests/unit/test_self_hosting_scenario_map.py` fails if a scenario is missing
here, or a case named here has no row in its own catalog or no test.

| Story | Scenario | Checked by |
| --- | --- | --- |
| ST1 | Install on the isolated network | Not proven yet: no install has run on an isolated network (task 002-03). FULL-01 and FULL-02 install the chart on a local kind cluster that can reach the internet and open sign-in over HTTPS; SHAPE-01 shows every PostgreSQL install image is pinned by digest. |
| ST2 | The install may pull from the registry | Not proven yet: no install has run through temporary registry access that was then closed (task 002-03). SHAPE-01 shows every image and the gateway chart are pinned, so the registry is the only source the chart names. |
| ST2 | Runs where only the models are reachable | Not proven yet: no install has run with only model endpoints reachable, and browser and device sign-in, the real coding runtime binary and the gateway image have not run under the outbound guard (task 002-03). EGR-01, EGR-02, EGR-11, EGR-12, EGR-15 and EGR-18 show the server and CLI contact only declared places; NETPOL-04, NETPOL-05 and NETPOL-10 render egress limited to DNS, databases and listed model endpoints. |
| ST2 | The web UI loads from inside | OFF-01, OFF-02, OFF-03, OFF-04, OFF-05, OFF-06, OFF-UI-01, OFF-UI-02 |
| ST3 | A local model works like a cloud one | Not proven yet: no run has asked an in-cluster model through Keeplane's gateway on an isolated network, so nothing shows the work stays inside it (task 002-03). On the current revision CI asks an in-cluster fixture model through the managed gateway on a kind cluster that can reach the internet: K8S-02 and K8S-03. The earlier kind trials FULL-07 and EXEDGE-03 ran on older chart revisions; EGR-12 shows in CI that the gateway adapter reaches only the address it is given. |
| ST3 | The managed gateway always requires keys | SHAPE-08, PKG-04 (Helm refuses the install without the key Secret, run in CI; the owner's rule from governance issue #47), SHAPE-07 (the rendered gateway checks a key for model calls and management). Supporting, not run in CI: GW-KEY-01, GW-KEY-02, GW-KEY-03 (the pinned gateway image refuses calls without the right key, using a hand-written strict-keys configuration, not the chart's). |
| ST4 | One gateway copy stops | K8S-01, K8S-03 and K8S-04 (run in CI on kind: two managed gateway copies are ready, one is deleted, and once the Service drops it ten new questions all get the fixture answer from the survivor; both copies are ready again afterwards), K8S-07 (registering the model again after recovery works on every try). A reply already streaming from the stopped copy is not exercised. Supporting: SHAPE-10 and SHAPE-13 render two copies and their disruption budget; FULL-08 is not run in CI. |
| ST5 | We already run the gateway | K8S-05, K8S-06 and K8S-17 (run in CI on kind: Keeplane installed against a separately installed agentgateway creates no gateway of its own, registers and approves a model there and gets its answer; sign-in and the admin APIs work; the two gateways' model lists stay separate), K8S-10 to K8S-13 (its install first checks the supplied gateway's version, model APIs and a fixture answer, and refuses a wrong version or an absent model before any change). The supplied gateway is the upstream chart in the same cluster, not a customer's installation. Supporting: SHAPE-06, SHAPE-09 and PKG-02 render no gateway of Keeplane's own; EXEDGE-01, EXEDGE-03 and EXIST-03 ran on older chart revisions. |
