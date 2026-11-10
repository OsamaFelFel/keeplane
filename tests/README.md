# Tests

| Folder | Purpose |
| --- | --- |
| `unit/` | Isolated Python rules, React form behavior and built web UI asset checks |
| `integration/` | Django storage, transactions, gateway contracts and chart configuration |
| `e2e/` | Journeys through running applications and deployment environments |
| `browser/` | Playwright interaction, accessibility and reviewed visual baselines |
| `fixtures/` | Deterministic services, data, manifests and container probes |
| `support/` | Shared clients, reporting and environment helpers |

Python checks use pytest discovery. `pytest` runs checks that need no live
application; checks marked `live`, `kubernetes` or `optional` require explicit
selection and the prerequisites in the [test guide](../docs/guide/regression-local.md).
Chart and Kubernetes checks find Helm 3 through `tests/support/helm.py`:
`KEEPLANE_HELM_BIN` when set, otherwise `helm` on `PATH`. Without Helm they are
skipped with a reason that names `KEEPLANE_HELM_BIN`; a wrong
`KEEPLANE_HELM_BIN` fails the run.
CI runs the unit and integration checks as parallel shards listed in
`tests/support/shards.py`; every test file belongs to exactly one, and
`pytest tests/unit tests/integration --shard <name>` runs one shard locally.
The separate `live-preview.yml` workflow starts the protected Docker preview
with `deploy/local/up.py` on a hosted runner and runs the live gateway cases
that need it: the [CLI sign-in](e2e/preview-sign-in-live-cases.md), the
[project classes](e2e/project-classes-live-cases.md), the
[down-model retry](integration/native-runtime-outage-cases.md), the
[model setup on the running gateway](e2e/model-setup-live-cases.md) and, with the
pinned coding runtime, the [developer journey](e2e/developer-journey-cases.md)
cases. A second
job in the same workflow builds the `detection` app image, starts the preview
the same way and runs the [personal-data detection](e2e/personal-data-live-cases.md)
cases with `KEEPLANE_PERSONAL_DATA_DETECTION=1`. The `release-journey` job
of `checks.yml` runs the same developer journey, DEV-01 to DEV-08, on two
disposable PostgreSQL installs with two app copies, one with the customer's own
gateway and one with the managed gateway (the
[release journey](e2e/developer-journey-release-cases.md) cases). A case that
is skipped or never runs fails its job.
Each spec's scenario map names the cases that prove every scenario, and a
unit test fails when a scenario is missing or a named case has no test:
Spec 002 [self-hosting](e2e/self-hosting-cases.md), 003
[accounts](e2e/accounts-cases.md), 004
[models and routing](unit/models-routing-cases.md), 005
[data classes](e2e/data-classes-cases.md), 006 [Audit](e2e/audit-cases.md)
and 009 [Developer CLI](e2e/developer-cli-cases.md). The Spec 002 and 009 maps
count a scenario as proven only by checks CI runs on the current revision.
In-process tests hash passwords with the application's PBKDF2 algorithm at a
lower round count (`tests/support/password_hashing.py`); processes started
with the application settings keep the full count.
Readable cases stay beside their relevant suites. Fixtures contain test inputs;
generated reports, logs and traces go under ignored `test-results/` or CI artifacts.
Each pytest invocation gets a fresh `test-results/pytest/` subdirectory. Set
`KEEPLANE_TEST_REPORT_DIR` to choose a fresh report directory explicitly.

Use `tests/run_regression.py` for the full configured environments. Test reports,
logs and traces stay out of Git. Earlier run notes
remain available at [their recorded commit](https://github.com/OsamaFelFel/keeplane/tree/6cf7bfc2a3defce262a2da1fe526a2d37fe33cc6/tests).

## Sign-in restart and outage checks in CI

The **sign-in-outage** job in `.github/workflows/checks.yml` builds the
PostgreSQL app image with CLI sign-in and runs
`e2e/test_sign_in_restart_outage.py` on a disposable Compose install of its own,
with a customer-run gateway ([cases](e2e/sign-in-restart-outage-cases.md)). It
fails if any case is skipped or doesn't run.

## Kubernetes live checks in CI

The **Kubernetes live checks** workflow (`.github/workflows/kubernetes-live.yml`)
runs on every pull request and on `main`. On a GitHub runner it installs pinned
kind, kubectl and Helm (each checked against a recorded SHA-256), runs
`deploy/local/kind-up.sh` with `KEEPLANE_KIND_QWEN=off`,
`KEEPLANE_KIND_LOAD_IMAGES=off` and `KEEPLANE_KIND_PROTECTED=on`, which builds the app
images and installs the chart three times on one kind cluster: the SQLite trial
with its managed gateway (two copies and the installer-made key Secret), the
same against a separately installed gateway, and the protected developer
release (PostgreSQL, CLI sign-in and the model enroller behind ingress-nginx at
`https://keeplane.kind.test`). It then runs the test files on the workflow's `LIVE_TESTS`
line: `e2e/test_local.py`, `e2e/test_kind.py`, `e2e/test_kind_private_ca.py`
(the fixture provider over HTTPS with a test CA the chart's
`trust.extraCaBundle` adds),
`e2e/test_gateway_secret_rotation.py`, `e2e/test_existing_gateway_preflight.py`,
`e2e/test_gateway_down.py` and `e2e/test_gateway_copy_stop.py`, which stops one
managed gateway copy mid-stream and during admin model changes, then brings it
back and checks it serves the current models. Then, in Alpine with the pinned
coding runtime, it runs the file on its `RUNTIME_LIVE_TESTS` line,
`e2e/test_kind_protected.py` ([cases](e2e/kubernetes-developer-cases.md)):
device sign-in and `keeplane code` through the protected release's public
address, on a shared key, a developer's own key and a refused own key. The job fails if any of them is skipped,
fails or reports an incomplete case set. Reports, the JUnit file and the
cluster's state and logs are uploaded as the `kubernetes-live-<commit>`
artifact.

The cluster has kind's default network plugin, which does not enforce
NetworkPolicy. The SQLite trial has no ingress: its app is reached through
kind's NodePort mapping and a port-forward. The network policy, ingress, full chart
(FULL, EXEDGE), browser and Qwen cases are not run there.

The same workflow's second job, **Chart on an isolated kind network**, runs
alongside it. It creates its own kind cluster with Calico (which enforces
NetworkPolicy) and ingress-nginx, both pinned by manifest checksum and image
digest, and an internal registry on the same network that holds a copy of
every image the install uses, which the node pulls through. It installs the
chart in managed mode with every network policy on, and
runs `e2e/test_kubernetes_isolated.py`. That test closes the cluster's outside
access on the runner except one model provider, closes outside name lookups
in the node, restarts every Keeplane pod and then the node, removes every
image the install brought from the node and starts it again from the internal
registry, and runs the [isolated-network cases](e2e/kubernetes-isolated-cases.md)
(ISO). It refuses any context other than `kind-keeplane-isolated` and changes
the runner's firewall, so run it only there. The job fails on any skipped or
missing case and uploads the `kubernetes-isolated-<commit>` artifact.

The kind tests take their kubeconfig from `KEEPLANE_KUBECONFIG` (default
`/private/tmp/keeplane-kind-kubeconfig` on macOS, `/tmp/keeplane-kind-kubeconfig`
elsewhere) and the trial's first-admin password from `KEEPLANE_RUNTIME_DIR`
(see `support/client.py`). They refuse any context other than `kind-keeplane`.
