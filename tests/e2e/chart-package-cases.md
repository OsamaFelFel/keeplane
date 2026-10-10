# Helm packaging cases

Run `python3 tests/e2e/test_chart_package.py --output <new JSON path>` with Helm 3 available. Set `KEEPLANE_HELM_BIN` when it is outside `PATH`. The cases render charts locally; they do not claim a production installation.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| PKG-01 | Lint and render the managed local chart. | The app has no Kubernetes API token, uses the default seccomp profile, and receives its private gateway key Secret; the managed gateway is present. |
| PKG-02 | Render existing-gateway mode with its URL and key Secret. | The preflight Job and app both use the key Secret, the Job has a stable label for a customer-owned gateway policy, and no managed gateway Deployment is installed. |
| PKG-03 | Set private image-pull credentials and app CPU/memory requests. | Both app and preflight receive those pod settings in the rendered manifests. |
| PKG-04 | Request conflicting gateway modes or turn on the local protected trial without a key Secret. | Helm rejects the values before installation. |
| PKG-05 | Render managed gateway ingress isolation, then try that policy in existing-gateway mode. | The policy selects only this release's gateway pods, admits only its app pods on port 4000, and refuses to claim control over a customer-supplied gateway. Rendering alone does not prove enforcement. |
| PKG-06 | Enable a TLS Ingress for managed and existing-gateway modes, then omit its TLS Secret or keep the local NodePort. | One host routes to the Keeplane app Service in both modes, never directly to the gateway. The chart rejects missing TLS settings and a second public NodePort. An ingress controller must still prove HTTPS behavior. |
| PKG-07 | Render the protected local values for the customer-run gateway app. | It has its own account and approval storage, first-admin Secret and private app Service, while no second gateway Deployment is rendered. |

Run the separate Kubernetes regression for actual readiness, model traffic and supplied-gateway preflight. Full-product NetworkPolicy and TLS enforcement, production state and release image clearance remain open.
