# Tests

- `unit/`: focused Python and React behavior checks.
- `e2e/`: API, storage, running-stack and deployment checks with readable cases.
- `browser/`: Playwright flows and reviewed screenshot baselines.
- `fixtures/`: reusable, deterministic test services and data.

See the [test guide](../docs/guide/regression-local.md) for commands and CI coverage.
Generated reports and traces go in ignored `test-results/` directories or CI artifacts.
Keep failures and identify unrun checks in the PR summary.

Historical Markdown reports remain for their explanations and links. Their raw
JSON/text reports can be read at [commit de0aba5](https://github.com/OsamaFelFel/keeplane/tree/de0aba5f8052fbbec55a2060309812812f09588e/tests).
