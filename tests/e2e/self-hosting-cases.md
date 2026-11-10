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
- The isolated network: ISO the [isolated-network cases](kubernetes-isolated-cases.md).

A render check runs `helm template`. When Helm refuses values there, `helm install`
refuses the same values, because both evaluate the templates before anything
reaches the cluster. Any other render result shows what the chart asks Kubernetes
to create, not what a cluster does with it, so a render check alone never proves
a live install here. A scenario counts as proven only by checks that run on the
current revision in CI, and never by render checks alone; the one exception is
Helm's install refusal for the managed gateway's keys, which is the refusal itself.
The **Kubernetes live checks** workflow (`.github/workflows/kubernetes-live.yml`)
installs the chart on a kind cluster on every revision and runs the test files on
its `LIVE_TESTS` line; their K8S cases (K8S-01 to K8S-13 and K8S-17 to K8S-21) count as CI
checks. That cluster can reach the internet, has no ingress controller and does
not enforce NetworkPolicy. The same workflow's isolated-network job has its own
`LIVE_TESTS` line and does the same for its ISO cases on
a kind cluster that enforces NetworkPolicy, behind an ingress controller, with
outside access closed except one model provider. The other K8S cases, FULL, EXEDGE, EXIST and GW-KEY
are not run in CI. The live trials ran on a local kind cluster or Docker with
outside access, not on an isolated network, and a trial recorded on an earlier
chart revision is named as the closest evidence, not as proof.

`tests/unit/test_self_hosting_scenario_map.py` fails if a scenario is missing
here, or a case named here has no row in its own catalog or no test.

| Story | Scenario | Checked by |
| --- | --- | --- |
| ST1 | Install on the isolated network | Proven on the local-trial install mode only (`app.localTrial.enabled`, with the managed gateway), installed with every network policy on (ISO-01, ISO-02, ISO-03, ISO-04, ISO-09). Outside access is then closed except one model provider, and the web UI opens through the ingress controller from the runner and from a pod inside the network, also after every pod and the node restart. The PostgreSQL install has not run on the closed network (task 002-03): FULL-01 and FULL-02 install it on a kind cluster with outside access, and SHAPE-01 shows every PostgreSQL install image is pinned by digest. |
| ST2 | The install may pull from the registry | ISO-01, ISO-02, ISO-03, ISO-09 prove it on one node that keeps the images it pulled: the install pulls its pinned images while the registry is reachable; once it is closed, a pull of an image the node fetched just before closing fails, and every Keeplane pod, the ingress controller and the same node restart from the images already cached on it. Not proven yet: a fresh node starting with the registry closed, and an internal registry mirror serving the images ([ADR 009](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0009-isolated-network.md), task 002-03). SHAPE-01 shows every image and the gateway chart are pinned, so the registry is the only source the chart names. |
| ST2 | Runs where only the models are reachable | Not proven yet: only part of release 1 has run with only model endpoints reachable. On the isolated kind network an admin signs in, adds a cloud model with a shared key and asks it, and asks the managed gateway's model inside the cluster, and the app and gateway reach nothing else (ISO-05, ISO-06, ISO-07, ISO-08, ISO-09). Still missing there: the PostgreSQL install, the developers' protected model path and CLI, browser and device sign-in, the coding runtime, detection, held records, audit and the other admin screens (task 002-03). EGR-01, EGR-02, EGR-11, EGR-12, EGR-15 and EGR-18 show the server and CLI contact only declared places; NETPOL-04, NETPOL-05 and NETPOL-10 render egress limited to DNS, databases and listed model endpoints. |
| ST2 | The web UI loads from inside | OFF-01, OFF-02, OFF-03, OFF-04, OFF-05, OFF-06, OFF-UI-01, OFF-UI-02 |
| ST3 | A local model works like a cloud one | Not proven yet: no run records every place the work went while the in-cluster model answered, so nothing yet proves the work stays inside the network (task 002-03). Closest on the isolated network: ISO-06 asks the in-cluster fixture model through the managed gateway with outside access and outside name lookups closed, and the outside model provider's call count stays the same; ISO-07 shows the app and the gateway copy reach the model endpoints and nothing else. On the current revision CI also asks an in-cluster fixture model through the managed gateway on a kind cluster that can reach the internet: K8S-02 and K8S-03. The earlier kind trials FULL-07 and EXEDGE-03 ran on older chart revisions; EGR-12 shows in CI that the gateway adapter reaches only the address it is given. |
| ST3 | The managed gateway always requires keys | SHAPE-08, PKG-04 (Helm refuses the install without the key Secret, run in CI; the owner's rule from governance issue #47), SHAPE-07 (the rendered gateway checks a key for model calls and management). Supporting, not run in CI: GW-KEY-01, GW-KEY-02, GW-KEY-03 (the pinned gateway image refuses calls without the right key, using a hand-written strict-keys configuration, not the chart's). |
| ST4 | One gateway copy stops | K8S-01, K8S-03 and K8S-04 (run in CI on kind: two managed gateway copies are ready, one is deleted, and once the Service drops it ten new questions all get the fixture answer from the survivor; both copies are ready again afterwards), K8S-07 (registering the model again after recovery works on every try). K8S-18 (run in CI on kind: a reply already streaming from a copy that is force-stopped ends with an error or without its end marker, never as a shorter answer marked complete, and the same request sent again through the gateway Service gets the whole answer from the surviving copy). K8S-19 to K8S-21 (run in CI on kind: with one copy stopped, narrowing a model's classes and removing a model are saved at once, while adding a model or widening its classes is refused with the copy-readback message and nothing saved; once the copy is back both succeed). Supporting: SHAPE-10 and SHAPE-13 render two copies and their disruption budget; FULL-08 is not run in CI. |
| ST5 | We already run the gateway | K8S-05, K8S-06 and K8S-17 (run in CI on kind: Keeplane installed against a separately installed agentgateway creates no gateway of its own, registers and approves a model there and gets its answer; sign-in and the admin APIs work; the two gateways' model lists stay separate), K8S-10 to K8S-13 (its install first checks the supplied gateway's version, model APIs and a fixture answer, and refuses a wrong version or an absent model before any change). The supplied gateway is the upstream chart in the same cluster, not a customer's installation. Supporting: SHAPE-06, SHAPE-09 and PKG-02 render no gateway of Keeplane's own; EXEDGE-01, EXEDGE-03 and EXIST-03 ran on older chart revisions. |
