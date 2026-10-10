# Customer-run gateway behind TLS and Calico

**Edition:** Open Source. Run `python3 tests/e2e/test_full_existing_edge.py --output tests/e2e/runs/<new-result>.json` from the repository root against the separate `kind-keeplane-netpol` cluster. The verifier installs the upstream gateway in one disposable namespace and Keeplane's existing-gateway chart in another. It removes both namespaces and the local port-forward. The regular Docker and kind previews are not changed.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| EXEDGE-01 | Install the pinned upstream gateway independently, apply its ingress policy allowing Keeplane's app and labeled preflight pods, then install Keeplane in existing-gateway mode. | Keeplane's gateway preflight passes under the policy and its namespace contains only the Keeplane app Deployment. |
| EXEDGE-02 | Visit Keeplane through verified HTTPS, sign in as the first admin, and read the identity API. | Anonymous access redirects to sign-in; the session and identity API succeed. |
| EXEDGE-03 | With the customer-owned Calico ingress policy active, register a local fixture model through Keeplane, then ask that model. | The app can reach the gateway under the policy, registration succeeds, and the model answers through the signed-in app route. |
| EXEDGE-04 | From an unrelated pod in Keeplane's namespace, call the gateway directly. | Calico blocks the network connection. |
| EXEDGE-05 | Request the gateway's model route from Keeplane's public HTTPS address. | The app redirects to sign-in; the gateway route is not published. |

The customer-owned ingress policy is applied **before** the installation preflight in the final trial. Kubernetes namespace permissions must prevent untrusted actors from creating pods with the allowed app or preflight labels. The test does not prove project identity, data-class rules, gateway artifact licensing, provider-direct egress control, production storage or compatibility with other CNIs and ingress controllers.
