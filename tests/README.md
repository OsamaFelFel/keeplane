# Tests

| Folder | Purpose |
| --- | --- |
| `unit/` | Isolated Python rules and React form behavior |
| `integration/` | Django storage, transactions, gateway contracts and chart configuration |
| `e2e/` | Journeys through running applications and deployment environments |
| `browser/` | Playwright interaction, accessibility and reviewed visual baselines |
| `fixtures/` | Deterministic services, data, manifests and container probes |
| `support/` | Shared clients, reporting and environment helpers |

Python checks use pytest discovery. `pytest` runs checks that need no live
application; checks marked `live`, `kubernetes` or `optional` require explicit
selection and the prerequisites in the [test guide](../docs/guide/regression-local.md).
Readable cases stay beside their relevant suites. Fixtures contain test inputs;
generated reports, logs and traces go under ignored `test-results/` or CI artifacts.

Use `tests/run_regression.py` for the full configured environments. Keep selected
durable verification summaries under `docs/verification/`. Earlier run notes
remain available at [their recorded commit](https://github.com/OsamaFelFel/keeplane/tree/6cf7bfc2a3defce262a2da1fe526a2d37fe33cc6/tests).
