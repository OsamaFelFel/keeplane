# Chart protected access cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_protected_access.py`
(tasks 004-01 and 002-02, Spec 004 ST10 and ST23–ST25, Spec 002 ST1 and ST4,
[ADR 016](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0016-control-plane-stack.md),
[ADR 018](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0018-gateway-runtime-policy.md),
[ADR 027](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0027-model-enroller.md)).
All cases but PA-06 render the chart with `helm template --namespace keeplane`
and need Helm 3.19 or newer, found through `KEEPLANE_HELM_BIN`, else `helm` on
`PATH`. Without Helm they are skipped, and a skipped case is not a pass. PA-06
reads only the values file and the guides and always runs.

With the model enroller on, each managed gateway copy runs Keeplane's
protected runtime, whose listener is port 5000 with one route,
`POST /v1/chat/completions`. These cases check how developers' CLIs reach it:
through Keeplane's one public address, on one exact path, with every gateway
management port private. Installs use the managed PostgreSQL values of the
[installation shape cases](chart-installation-shape-cases.md), release `pg`,
with the enroller settings of the
[model enroller cases](chart-model-enroller-cases.md). The guide is
[how developers reach protected models](../../docs/guide/kubernetes-installation-reference.md#how-developers-reach-protected-models).

Rendering proves what the chart asks Kubernetes to create. It does not prove
that a cluster routes or enforces it: a live run through an ingress controller
and a NetworkPolicy-enforcing plugin, on the real gateway image, is not part of
these cases.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| PA-01 | Render the managed and existing-gateway PostgreSQL installs and both local trials with the default values. | No `-gateway-runtime` Service renders, no Service carries port 5000, no Ingress path is `/v1/chat/completions` or goes to port 5000, and nothing renders `port: 5000`. |
| PA-02 | Turn the enroller on and list every Service and declared container port. | One new Service, `pg-gateway-runtime`: an ordinary `ClusterIP` (not headless), selecting exactly the gateway copies' pod labels, with one port, `protected`, TCP 5000 to 5000. The Services are then exactly `pg-app` (3000), `pg` (4000), `pg-gateway-copies` (4000) and `pg-gateway-runtime` (5000): no other Service gains 5000 and none carries the admin (15000), stats (15020) or readiness (15021) port. The declared container ports are the same as without the enroller. |
| PA-03 | With the enroller and the chart's Ingress (plus an annotation), read the Ingress; then turn the Ingress off. | One Ingress, `pg-app`, one host with TLS as before, and exactly two paths: `/v1/chat/completions`, `Exact`, to `pg-gateway-runtime` port 5000, then `/`, `Prefix`, to `pg-app` port 3000. No path goes to 4000, 15000, 15020 or 15021. With the Ingress off no Ingress renders and the Service still does, for an installer's own edge. |
| PA-04 | Turn on the gateway ingress policy with an ingress controller's namespace and pod labels in `networkPolicy.publicEntry`, without and with the enroller; then with pod labels only; then also the app ingress policy. | Without the enroller the policy admits only this release's app pods on TCP 4000, as before. With it, it also admits exactly the public entry's namespace and pod labels on TCP 5000, and nothing else; the app pods still reach only 4000. With pod labels only, the 5000 rule stays inside the release namespace. The app ingress policy still admits only TCP 3000. |
| PA-05 | Turn on the enroller and the gateway ingress policy with an empty `publicEntry`, then with empty label maps; then turn the policy off; then render the gateway policy without the enroller and with no `publicEntry`. | Helm refuses the first two, with a message naming `gateway.enroller with networkPolicy.gatewayIngressEnabled needs networkPolicy.publicEntry` and port 5000. Without the gateway policy it renders. Without the enroller the gateway policy needs no public entry, as before. |
| PA-06 | Read `values.yaml` and the installation reference. | The values file names `<release>-gateway-runtime`, `/v1/chat/completions`, `https://<ingress.host>/v1` and `TCP 5000` and no longer says the Ingress publishes only the app. The reference's Model enroller section explains the Service, the exact Ingress path, `https://<host>/v1` as the CLI's `--gateway`, `networkPolicy.publicEntry` and ADR 016; its Ports section names the Service and path. It no longer says the port has no Service, that how developers reach it is not decided, that the gateway is never an Ingress backend or that the Ingress routes only to the app. |
