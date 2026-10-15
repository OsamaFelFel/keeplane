# Shared PostgreSQL accounts and settings

**Edition:** Open Source; Enterprise uses the same base identity and storage contract.

Keeplane can run its existing API against PostgreSQL. UUID accounts, native
Django sessions, sign-in budgets, account operation IDs, Editions preferences,
model approvals, data classes and Audit records share one database. The Docker
and kind review previews still use SQLite. The chart has an explicit PostgreSQL
integration mode. Production database operations and the release package remain
in progress.

## Configure a clean installation

Install the pinned API requirements and
`components/control-plane/requirements-postgres.txt`. The latter uses the
replaceable pure-Python Psycopg 3.3.6 distribution and needs an installed `libpq`.
The default preview image does not include that optional driver. Build the
`postgres` target for chart integration:

```sh
docker build --target postgres -t keeplane-postgres:local \
  -f components/control-plane/Dockerfile .
```

It builds the unmodified Psycopg C extension from hash-verified source and
dynamically links Alpine libpq 18.6-r0. Compiler tools stay in the build stage.
The image includes both driver source archives, notices and a runtime package
inventory under `/usr/share/keeplane/`. Retain these when distributing it and
allow replacement of the drivers. Complete native/base-image source and notice
inventory remains release work. See the [package records](../../components/control-plane/licenses/README.md)
and [Psycopg installation choices](https://www.psycopg.org/psycopg3/docs/basic/install.html).

Configure every app replica and the one-off migration process:

| Setting | Value |
| --- | --- |
| `KEEPLANE_DATABASE_HOST` | Private PostgreSQL hostname; enables the complete PostgreSQL store |
| `KEEPLANE_DATABASE_PORT` | Port, default `5432` |
| `KEEPLANE_DATABASE_NAME` | Database name |
| `KEEPLANE_DATABASE_USER` | Database user |
| `KEEPLANE_DATABASE_PASSWORD_FILE` | Mounted password file |
| `DJANGO_SECRET_KEY_FILE` | Same private signing-secret file on every replica; at least 48 characters |
| `FIRST_ADMIN_PASSWORD_FILE` | Same infrastructure password file on every replica; 12–256 characters |
| `PUBLIC_ORIGIN` | Browser-facing HTTPS origin; sets Secure cookies and CSRF trust |
| `PUBLIC_ORIGIN_ALIASES` | Explicit additional browser origins, if needed |
| `KEEPLANE_DATABASE_SSLMODE` | Defaults to `verify-full` |
| `KEEPLANE_DATABASE_SSLROOTCERT_FILE` | Mounted database CA certificate when using a private CA |

Keep credentials in mounted Secrets rather than committed configuration,
command arguments or logs. PostgreSQL mode requires its stable signing secret
and database configuration; it never falls back to SQLite or a random signing
key. The API fixture disables database TLS. The separate chart fixture tests
verified TLS, wrong-hostname/CA refusal and a server that rejects plaintext.

Run `python /app/manage.py migrate --noinput` once before starting the app.
Serving processes never migrate. `python /app/manage.py check` validates the
configuration; `python /app/manage.py makemigrations --check --dry-run` checks
schema consistency. This pre-release stage supports a clean database rather
than an upgrade from the SQLite trial.

## Sessions, recovery and rotation

Sessions expire on the server after eight hours. Every protected request loads
the current account and role. Promotion affects an existing session immediately;
demotion and removal revoke sessions. Logout on one replica takes effect on the
others. The first admin cannot be removed or demoted through the API.

Break-glass sign-in commits its session and mandatory Audit record together
before returning a cookie. If the record cannot be written, no session commits.
Settings changes and their enabled Audit records also commit or roll back
together. All copies reserve from one per-username five-attempt, one-minute
budget before checking a password. Casing changes and app restarts preserve it;
unavailable storage refuses sign-in.

Update the first-admin credential file consistently on every replica, then
restart a copy. Rotation preserves the UUID, clears that account's exhausted
budget and revokes old sessions. Never leave different configured passwords on
replicas that may restart.

Back up the complete database and retain the matching signing secret separately.
Restore into a fresh database and point all replicas at it. Integration cases
prove identity, sessions, settings, approvals and Audit survive this operation.
Production backup scheduling, retention, database availability, volume semantics
and review-preview cutover remain release work.

## Install the chart against an operated database

Use [the example values](../../deploy/postgres/values.example.yaml). Provision a
private database owned by a migration role and a separate app login. Neither
role needs superuser, database creation or role creation permission. Revoke
`PUBLIC` database access and schema creation. Grant the app only `CONNECT` on
this database, `USAGE` on its schema, and table `SELECT, INSERT, UPDATE, DELETE`
plus sequence `USAGE, SELECT`. Set the migration role's default privileges so
new tables and sequences receive those grants. Keep database ownership and DDL
permission with the migration role. See [PostgreSQL privileges](https://www.postgresql.org/docs/16/ddl-priv.html).

Create namespaced Secrets with these keys:

| Values field | Secret contents |
| --- | --- |
| `app.postgres.credentialsSecret` | `password` for the restricted app role |
| `app.postgres.migration.credentialsSecret` | `password` for the separate migration role |
| `app.postgres.identitySecret` | `first-admin-password` and stable `signing-secret` |
| `app.postgres.caSecret` | `ca.crt` for the database's issuing CA |
| `gateway.keysSecret` | `runtime-key` and separate `admin-key` |

The chart mounts passwords as files and always uses database `verify-full`;
the configured hostname must match the server certificate. See
[PostgreSQL TLS verification](https://www.postgresql.org/docs/16/libpq-ssl.html).
Its pre-install/pre-upgrade Job runs explicit migrations with the separate
credential, which is never mounted in app pods. Failure stops the Helm operation.
Do not run concurrent Helm upgrades. For a future incompatible migration,
coordinate old-worker shutdown and backup before running it; automatic schema
rollback is not supplied. Set `app.postgres.migration.enabled=false` only when
an external migration process has already prepared the schema.

`app.replicaCount` may exceed one in PostgreSQL mode. `/health/ready` checks the
shared settings table and returns 503 during database loss; `/health/app` keeps
the process alive for recovery. Database failure does not trigger a liveness
restart. SQLite trial mode requires one copy and cannot be combined with
PostgreSQL.

Supply an existing provider-key PVC. Multiple nodes need a volume that supports
the required shared reads/writes; the single-node test's RWO claim does not prove
that production property. Managed gateways need their read-only mount configured
separately. Customer-gateway provider credentials remain a separate integration
contract. This chart does not install or operate PostgreSQL, choose a database
operator, schedule backups or claim a release-ready gateway policy boundary.
