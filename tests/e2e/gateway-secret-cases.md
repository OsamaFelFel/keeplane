# Gateway PostgreSQL Secret binding cases

Run `python3 tests/e2e/test_gateway_secret_binding.py --output <new JSON path>` from the repo root. The test creates a private, disposable Docker network with the exact pinned agentgateway 1.6.0 and PostgreSQL fixture images, then removes it. It uses the non-production password `fixture-only`; output records no URL or password. The [gateway config](gateway-secret/config.yaml) and [Helm overlay](gateway-secret/values.yaml) contain the `${TRIAL_DB_PASSWORD}` placeholder, not a credential.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GSECRET-01 | Start the gateway with a PostgreSQL URL containing `${TRIAL_DB_PASSWORD}` and give it the correct value as an environment variable. | The gateway becomes ready and answers its health endpoint. |
| GSECRET-02 | Start a second gateway with the same config but a wrong environment value. | It exits after PostgreSQL refuses authentication. This shows the placeholder is actually used. |
| GSECRET-03 | Render the Keeplane managed chart with a URL placeholder and `extraEnv` reading that variable from a Kubernetes Secret. | The rendered ConfigMap contains the placeholder and no password; the gateway Deployment references the Secret key. |
| GSECRET-04 | In the separate Calico kind cluster, install the exact upstream chart with a Kubernetes Secret containing the disposable database password. | The gateway Deployment becomes Ready, its health endpoint answers, and its live ConfigMap contains only the placeholder while the Deployment references the Secret. |

Run `python3 tests/e2e/test_gateway_secret_kind.py --output <new JSON path>` for GSECRET-04 after preparing the isolated cluster in [network-policy-cases.md](network-policy-cases.md). The script refuses another kubeconfig context and removes its disposable namespace. Its [PostgreSQL fixture](gateway-secret/kind-db.yaml) uses memory-backed storage and a test-only password; [upstream values](gateway-secret/upstream-values.yaml) reference the Secret key.

This is not a production database or a rotation test. A Kubernetes Secret is only a delivery mechanism; cluster encryption, RBAC, backup, rotation and a full Keeplane installation still need evidence.
