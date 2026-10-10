# Gateway database password in Kubernetes

The pinned agentgateway standalone chart can read the database password from a Kubernetes Secret. Keep an environment placeholder in the PostgreSQL URL and use the chart's `extraEnv` to load the password. The [Docker, Helm and isolated kind cases](../../tests/e2e/runs/2026-10-10-gateway-secret-binding.md) verify this with chart v1.6.0.

Prepare a Secret in the Keeplane namespace from an operator-controlled file:

```sh
kubectl -n keeplane create secret generic keeplane-gateway-db --from-file=password=/secure/path/to/url-encoded-password
```

Set the chart values without placing the password in the values file or Helm command line:

```yaml
agentgateway-standalone:
  database:
    postgres:
      url: 'postgresql://keeplane:${KEEPLANE_DB_PASSWORD}@postgres.example.internal:5432/keeplane'
  extraEnv:
    - name: KEEPLANE_DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: keeplane-gateway-db
          key: password
```

The Secret's password field must contain a URL-encoded password because it is inserted into the URL's password segment; see [PostgreSQL's URI rules](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING). Check the rendered ConfigMap for the literal placeholder and the gateway Deployment for `secretKeyRef`; do not print the Secret value during verification. Rotate the Secret and restart the gateway replicas under a tested rollout procedure, then recheck model traffic. The disposable `deploy/local/values.yaml` contains a test password and is not a production values file.

This documents one tested credential-delivery mechanism. A release still needs a durable PostgreSQL service, Secret access controls, storage encryption policy, backup and rotation tests, image/license clearance and full two-replica rollout evidence.
