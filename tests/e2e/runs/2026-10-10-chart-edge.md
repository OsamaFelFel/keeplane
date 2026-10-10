# 10 October 2026 — one-address chart render

The [plain-English PKG-06 case](../chart-package-cases.md), [verifier](../test_chart_package.py) and [final render result](2026-10-10-chart-edge-origin.json) show an optional Kubernetes Ingress in managed and supplied-gateway modes. It routes the configured host and `/` prefix to the Keeplane app Service on port 3000, with an ingress class and an existing TLS Secret. It contains no gateway Service backend. In the protected local-trial app, enabling the Ingress sets `PUBLIC_ORIGIN` to its HTTPS host. Missing TLS settings and a simultaneous app NodePort are rejected. All six chart cases passed; the running previews were not changed.

The [first render](2026-10-10-chart-edge-render.json) failed PKG-06 because the test used the chart's incomplete default managed database URL. The [corrected render](2026-10-10-chart-edge-render-corrected.json) passed with local managed values. The final run added the HTTPS origin check.

This is a chart render, not a live ingress trial. An installed ingress controller must be tested for HTTPS, HTTP redirect, host routing, path restrictions and certificate handling. The proposed trusted project-bound runtime path is unresolved, so no gateway runtime path is exposed here. Gateway management, database and upstream components remain internal in the rendered chart. The chart is not a production package.
