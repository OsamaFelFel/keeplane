# Run the Kubernetes integration trial locally

This trial runs Keeplane at [http://127.0.0.1:13000](http://127.0.0.1:13000).
The Docker preview remains available at [http://127.0.0.1:3000](http://127.0.0.1:3000).
In the Models screen, choose **Add model**, enter `http://qwen:8080`, choose
**Find models**, select `qwen2.5-coder:0.5b`, and add it. Keeplane checks the
runner before registration. To test an answer, use the `/api/ask` example in
the [local model guide](local-preview.md) with port `13000`.

Install Docker, `kind`, `kubectl`, Helm and `rg`. Download the pinned Qwen model
as described in the [local model guide](local-preview.md), then run from the
repository root:

```sh
deploy/local/kind-up.sh
KEEPLANE_BASE_URL=http://127.0.0.1:13000 python3 tests/e2e/test_local.py
KEEPLANE_BASE_URL=http://127.0.0.1:13000 python3 tests/e2e/test_qwen.py
KEEPLANE_BASE_URL=http://127.0.0.1:13000 python3 tests/e2e/test_runner_flow.py
python3 tests/e2e/test_model_runtime.py --kind
python3 tests/e2e/test_kind.py
python3 tests/e2e/test_stack_lock.py
```

The setup script pulls pinned images and the first run requires registry
access. It builds Keeplane from the current source, creates a separate kind
cluster, loads the images into it, and starts Qwen from the checked model file.
Every Kubernetes and Helm command uses
`/private/tmp/keeplane-kind-kubeconfig`; your default Kubernetes context is
untouched. Set `KEEPLANE_HELM_BIN` if Helm is installed outside `PATH`, or
`KEEPLANE_KUBECONFIG` to keep the isolated kubeconfig elsewhere. Run the script
again after changing Keeplane's app or chart.

The managed install uses agentgateway's **official standalone Helm chart**,
version `v1.6.0`, with two gateway replicas and PostgreSQL-backed model
registration. Qwen is a real local model served by llama.cpp, while
`local-fixture` returns a fixed test answer. The PostgreSQL Deployment in `deploy/local` is a disposable test
fixture with a fixed test password and temporary storage. The app-only install
in the `keeplane-existing` namespace points to a separately installed upstream
agentgateway in `supplied-gateway`. That gateway has its own disposable
PostgreSQL and a pre-existing fixture model. Keeplane installs no gateway into
`keeplane-existing`, and the Kubernetes test registers another model through
Keeplane into this supplied gateway.

The app's Kubernetes readiness probe checks `/health/app`, which stays healthy
while the gateway is unavailable. `/health` still reports gateway dependency
health. This lets the Models page load its gateway warning and Try again control
instead of removing the admin UI from the Service. The isolated
[gateway-down cases](../../tests/e2e/kubernetes-cases.md) and
[run](../../tests/e2e/runs/2026-10-09-gateway-down.md) verify this behavior.

The checked-in chart dependency and lock file pin the upstream chart to
`v1.6.0`. The gateway and fixture container images are also pinned by digest.
The chart is an integration trial, not a production installation. Release
work remains for durable PostgreSQL, secret handling, external network
controls, production image clearance, node failure and upgrade testing.
The exact trial images, chart versions, kind node and Qwen model checksum are
recorded in [stack.lock.json](../../deploy/local/stack.lock.json). The lock
check compares those entries with the running Docker and kind installations;
it is not yet a customer release compatibility manifest.

The test procedures are in [Kubernetes cases](../../tests/e2e/kubernetes-cases.md),
with the [initial install run](../../tests/e2e/runs/2026-10-08-kind.md) and
[real Qwen browser run](../../tests/e2e/runs/2026-10-08-qwen-kind-ui.md).
The [separate supplied gateway run](../../tests/e2e/runs/2026-10-08-existing-gateway-registration.md)
records registration and catalog isolation in existing-gateway mode.
The [S8 runner flow run](../../tests/e2e/runs/2026-10-08-s8-runner-flow.md)
records live Add model checks in Docker and both kind modes.

## Inspect the running trial

Use the isolated kubeconfig for every command; the workstation's default
Kubernetes context may point to another cluster.

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane get pods,deploy,svc
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane-existing get pods
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n supplied-gateway get pods,deploy,svc
```

In the `keeplane-existing` app-only trial, the enabled runner address is
`http://model.supplied-gateway.svc.cluster.local:18080`. Its model is
`mock-local`, a fixed-answer fixture. The runner allowlist is configured by
the chart's `app.runnerUrls` value; it is a preview safeguard while the admin
page has no sign-in.

Agentgateway's own management UI is available through a local port forward.
Keep this command running in a terminal, then open
[http://127.0.0.1:14000/ui/llm/models](http://127.0.0.1:14000/ui/llm/models).
This trial UI has no sign-in, so the port forward binds only to loopback.

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane \
  port-forward service/keeplane 14000:4000 --address 127.0.0.1
```

To inspect the separate supplied gateway's `customer-fixture` catalog, run a
second port forward and open
[http://127.0.0.1:14001/ui/llm/models](http://127.0.0.1:14001/ui/llm/models).

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n supplied-gateway \
  port-forward service/supplied-gateway 14001:4000 --address 127.0.0.1
```

To inspect Qwen's *effective* context and sampler defaults, read the running
server. `/props` shows its active context and sampling defaults; `/v1/models`
also reports the model's training context. These are different limits.

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane \
  exec deploy/keeplane-app -- python -c 'import json,urllib.request; u="http://qwen:8080"; p=json.load(urllib.request.urlopen(u+"/props")); m=json.load(urllib.request.urlopen(u+"/v1/models"))["data"][0]; s=p["default_generation_settings"]; print({"active_context":s["n_ctx"],"training_context":m["meta"]["n_ctx_train"],"temperature":s["params"]["temperature"],"top_p":s["params"]["top_p"],"default_max_tokens":s["params"]["max_tokens"]})'
```

The current Qwen manifest requests a 4,096-token context and sets `-n 256`.
The running server currently reports `default_max_tokens: -1` in `/props`, but
the [model runtime regression](../../tests/e2e/test_model_runtime.py) verifies
that real completions stop at 256 tokens both directly and through
agentgateway. Treat completion usage and finish reason as the evidence for this
output limit. Keeplane's preview does not expose model sampling settings or a
context control in its UI yet.
