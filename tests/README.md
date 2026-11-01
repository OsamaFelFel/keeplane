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
