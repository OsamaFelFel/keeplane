# Production package diagnostics

These cases are release gates, not part of the passing local-preview regression. Run `python3 tests/e2e/test_production_package_gaps.py --output <new JSON path>` from the repo root. The probe uses only the chart's disposable local database URL and writes booleans, never the rendered URL or password.

| ID | Plain-English action | Release expectation |
| --- | --- | --- |
| PKG-GAP-01 | Render the pinned managed agentgateway chart with a password-bearing PostgreSQL URL and inspect the resulting ConfigMap without logging its contents. | A connection password is not present in a ConfigMap or other public chart output; the gateway reads it from a referenced Kubernetes Secret. |

The diagnostic records whether this expectation passes. A captured failure keeps the production package gate open without making the local Docker/kind regression fail.
