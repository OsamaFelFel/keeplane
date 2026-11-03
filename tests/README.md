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
that need it: the [project classes](e2e/project-classes-live-cases.md) and the
[down-model retry](integration/native-runtime-outage-cases.md) cases. A case
that is skipped or never runs fails that job.
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

## Kubernetes live checks in CI

The **Kubernetes live checks** workflow (`.github/workflows/kubernetes-live.yml`)
runs on every pull request and on `main`. On a GitHub runner it installs pinned
kind, kubectl and Helm (each checked against a recorded SHA-256), runs
`deploy/local/kind-up.sh` with `KEEPLANE_KIND_QWEN=off` and
`KEEPLANE_KIND_LOAD_IMAGES=off`, which builds the app
image and installs the chart twice on one kind cluster: with its managed gateway
(two copies and the installer-made key Secret) and against a separately
installed gateway. It then runs the test files on the workflow's `LIVE_TESTS`
line: `e2e/test_local.py`, `e2e/test_kind.py`,
`e2e/test_gateway_secret_rotation.py`, `e2e/test_existing_gateway_preflight.py`
and `e2e/test_gateway_down.py`. The job fails if any of them is skipped,
fails or reports an incomplete case set. Reports, the JUnit file and the
cluster's state and logs are uploaded as the `kubernetes-live-<commit>`
artifact.

The cluster has kind's default network plugin, which does not enforce
NetworkPolicy, and no ingress controller; the app is reached through kind's
NodePort mapping and a port-forward. The network policy, ingress, full chart
(FULL, EXEDGE), browser and Qwen cases are not run there.

The kind tests take their kubeconfig from `KEEPLANE_KUBECONFIG` (default
`/private/tmp/keeplane-kind-kubeconfig` on macOS, `/tmp/keeplane-kind-kubeconfig`
elsewhere) and the trial's first-admin password from `KEEPLANE_RUNTIME_DIR`
(see `support/client.py`). They refuse any context other than `kind-keeplane`.
