# Gateway PostgreSQL Secret binding cases

Run `.venv/bin/python -m pytest tests/e2e/test_gateway_secret_binding.py -m live` from the repo root. The test creates a private, disposable Docker network with the exact pinned agentgateway 1.6.0 and PostgreSQL fixture images, then removes it. It uses the non-production password `fixture-only`; output records no URL or password. The [gateway config](../fixtures/gateway-secret/config.yaml) and [Helm overlay](../fixtures/gateway-secret/values.yaml) contain the `${TRIAL_DB_PASSWORD}` placeholder, not a credential.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GSECRET-01 | Start the gateway with a PostgreSQL URL containing `${TRIAL_DB_PASSWORD}` and give it the correct value as an environment variable. | The gateway becomes ready and answers its health endpoint. |
| GSECRET-02 | Start a second gateway with the same config but a wrong environment value. | It exits after PostgreSQL refuses authentication. This shows the placeholder is actually used. |
| GSECRET-03 | Render the Keeplane managed chart with a URL placeholder and `extraEnv` reading that variable from a Kubernetes Secret. | The rendered ConfigMap contains the placeholder and no password; the gateway Deployment references the Secret key. |
| GSECRET-04 | In the separate Calico kind cluster, install the exact upstream chart with a Kubernetes Secret containing the disposable database password. | The gateway Deployment becomes Ready, its health endpoint answers, and its live ConfigMap contains only the placeholder while the Deployment references the Secret. |

Run `.venv/bin/python -m pytest tests/e2e/test_gateway_secret_kind.py -m live` for GSECRET-04 after preparing the isolated cluster in [network-policy-cases.md](network-policy-cases.md). The script refuses another kubeconfig context and removes its disposable namespace. Its [PostgreSQL fixture](../fixtures/gateway-secret/kind-db.yaml) uses memory-backed storage and a test-only password; [upstream values](../fixtures/gateway-secret/upstream-values.yaml) reference the Secret key.

Run `.venv/bin/python -m pytest tests/e2e/test_gateway_secret_rotation.py -m live` for the following cases in `kind-keeplane`. The script installs the Keeplane wrapper chart in a disposable namespace, uses generated credentials, and removes the namespace afterward. It first creates the gateway key Secret the chart requires for a managed gateway, so model calls use the runtime key and model registration uses the admin key.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GSECRET-05 | Install the managed wrapper chart before creating its database Secret. | Gateway pods cannot start and report a missing Secret; no gateway replica is Ready. |
| GSECRET-06 | Create the Secret and wait for PostgreSQL and both gateway replicas. | Both replicas become Ready; the live gateway ConfigMap and Helm manifest contain only the placeholder and Secret reference, with no password. |
| GSECRET-07 | Register a new model through the management API, then read and call it on each replica. | Both replicas retain the model and answer through the local fixture. |
| GSECRET-08 | Change the PostgreSQL role password, update the Secret, and restart both gateway replicas. | All gateway pods are replaced; the new password authenticates, the old one fails, and each new replica still lists and calls the model. |
| GSECRET-09 | Back up the database, stop the gateways, replace the disposable PostgreSQL pod, restore the backup, and start both replicas. | Both replicas list and call the saved model after restoration. |

These are disposable local credential and recovery tests. They do not prove uninterrupted rotation, durable storage, production backup policy, cluster encryption or RBAC. The fixture's PostgreSQL data is lost when its pod is replaced without a backup.
