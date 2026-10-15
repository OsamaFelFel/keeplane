# Gateway database password in Kubernetes

The pinned agentgateway standalone chart can read the database password from a Kubernetes Secret. Keep an environment placeholder in the PostgreSQL URL and use the chart's `extraEnv` to load the password. The [Docker, Helm and isolated kind cases](https://github.com/OsamaFelFel/keeplane/blob/6cf7bfc2a3defce262a2da1fe526a2d37fe33cc6/tests/e2e/runs/2026-10-10-gateway-secret-binding.md) verify this with chart v1.6.0.

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

The Secret's password field must contain a URL-encoded password because it is inserted into the URL's password segment; see [PostgreSQL's URI rules](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING). The actual PostgreSQL role password is the decoded value. Password files must have no trailing newline. Check the rendered ConfigMap for the literal placeholder and the gateway Deployment for `secretKeyRef`; do not print the Secret value during verification.

For rotation, change the database role password, replace the Secret's password field, and restart the gateway replicas so they load the new environment value. Updating a Secret alone does not update existing process environments. Recheck a model call on each replacement replica and confirm the old credential is refused. This sequence can interrupt new database connections while the replicas change; it does not promise uninterrupted rotation. Changing `POSTGRES_PASSWORD` in the PostgreSQL fixture does not change a role in an already initialized database.

## Local kind fixtures

`deploy/local/kind-up.sh` creates separate generated passwords for the managed and supplied-gateway databases. It keeps their files, with owner-only access, at `/private/tmp/keeplane-accounts-trial/gateway-db-password` and `supplied-gateway-db-password`. Each database namespace gets its own `keeplane-gateway-db` Secret. PostgreSQL and its gateway read that Secret, while the gateway ConfigMap and Helm values contain only `${KEEPLANE_DB_PASSWORD}`. The app-only existing-gateway installation gets no database credential.

Keep these files across setup runs. Losing a file is not a request to rotate the database: recover the matching file from the existing Secret before setup. Local PostgreSQL uses `emptyDir`, so replacing its pod loses its catalog. Its `Recreate` strategy avoids serving two independent temporary databases during replacement.

Older previews used a literal database password. The setup script refuses to replace that legacy fixture automatically. To migrate a preview worth keeping, stop its gateway replicas, save a private `pg_dump --clean --if-exists` backup, create its password Secret, replace the database fixture, restore the backup with `psql -v ON_ERROR_STOP=1`, and upgrade its gateway using the new values. Repeat for the separate supplied gateway. Verify the saved model catalog and actual model calls before discarding backups. A customer database needs its own approved backup and maintenance procedure.

The [rotation and recovery cases](../../tests/e2e/gateway-secret-cases.md) install the actual wrapper chart with two replicas in a disposable kind namespace. They check missing-Secret refusal, startup, registration, password rotation and catalog recovery from a database backup. The [12 October results](https://github.com/OsamaFelFel/keeplane/blob/6cf7bfc2a3defce262a2da1fe526a2d37fe33cc6/tests/e2e/runs/2026-10-12-database-secrets.md) also record the running-preview migration and TLS checks in both gateway modes.

This documents a local credential-delivery and recovery path. A release still needs durable PostgreSQL, Secret access controls, storage encryption policy, production backup and rotation procedures, image/license clearance and full replica policy evidence.
