# Helm packaging cases

Run `python3 tests/e2e/test_chart_package.py --output <new JSON path>` with Helm 3 available. Set `KEEPLANE_HELM_BIN` when it is outside `PATH`. The cases render charts locally; they do not claim a production installation.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| PKG-01 | Lint and render the managed local chart. | The app has no Kubernetes API token, uses the default seccomp profile, and receives its private gateway key Secret; the managed gateway is present. |
| PKG-02 | Render existing-gateway mode with its URL and key Secret. | The preflight Job and app both use the key Secret and no managed gateway Deployment is installed. |
| PKG-03 | Set private image-pull credentials and app CPU/memory requests. | Both app and preflight receive those pod settings in the rendered manifests. |
| PKG-04 | Request conflicting gateway modes or turn on the local protected trial without a key Secret. | Helm rejects the values before installation. |

Run the separate Kubernetes regression for actual readiness, model traffic and supplied-gateway preflight. NetworkPolicy enforcement, ingress, production state and release image clearance remain open.
