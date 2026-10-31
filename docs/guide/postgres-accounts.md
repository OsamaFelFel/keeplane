# Shared PostgreSQL accounts and settings

Keeplane can run its existing API against PostgreSQL. UUID accounts, native
Django sessions, sign-in budgets, account operation IDs, Editions preferences,
model approvals, data classes and Audit records share one database. The Docker
and kind review previews use the same Django ORM services with SQLite. The chart has an explicit PostgreSQL
integration mode. Production database operations and the release package remain
in progress.

## Configure a clean installation

PostgreSQL mode adds `components/control-plane/requirements-postgres.txt` to the
pinned API requirements. For a direct Python installation, install both sets and
`libpq` for Psycopg 3.3.6. The default preview image omits the optional driver.

For a manual image build, install Node.js 22.12 or newer with npm and prepare the
web UI first. The image copies the generated `components/admin-ui/dist` assets;
rebuild them whenever the UI changes. From the repository root:

```sh
npm --prefix components/admin-ui ci
npm --prefix components/admin-ui run build
```

The [local launcher](local-preview.md) prepares those assets automatically.
Build the `postgres` target for chart integration:

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

The final `preview` and `postgres` images omit `pip` and `ensurepip`. Install
dependencies while building an image, then rebuild to update them. Installer
notices remain under `/usr/share/keeplane/licenses/pip-<version>/`. The pinned
base layers still carry their original distribution obligations.

### Add CLI sign-in to the shared-database image

For the approved sign-in integration trial, build the combined target instead:

```sh
docker build --platform linux/amd64 --target postgres-cli-auth-trial \
  -t keeplane-postgres-cli-trial:local -f components/control-plane/Dockerfile .
```

It adds the hash-pinned sign-in dependencies to the PostgreSQL image, retaining
their original notices and the driver's source records. It contains neither
runtime Python installers nor a CLI agent binary. Normal image targets are unchanged.
The [source and notice obligations](../../components/control-plane/licenses/cli-auth-trial.md)
still apply; this target does not select a release distribution.

Configure the database and signing secret as below. Set
`KEEPLANE_CLI_OAUTH_ENABLED=1` and the installation's HTTPS `PUBLIC_ORIGIN` for
the migration, client-registration and serving processes. Before serving, run:

```sh
python /app/manage.py migrate --noinput
python /app/manage.py register_cli_client
python /app/manage.py register_cli_client --device
```

Missing dependencies or changed fixed clients fail rather than silently enabling
another sign-in flow.

To enable sign-in in the Helm installation, use the combined image's immutable
registry digest and set `app.cliSignIn.enabled=true`. It requires PostgreSQL and
the existing HTTPS app address. The migration Job registers both fixed clients
after migrating, using its separate database credential. Normal installs keep
sign-in off. Missing optional dependencies fail setup.

If `app.postgres.migration.enabled=false`, your database operator must run all
three commands above, with the same image and environment, before serving.
Readiness returns 503 while either fixed client is missing or differs; it does
not create or repair them. Registration refuses changed metadata, so review that
configuration before deliberately repairing it. A matching registration is safe
to repeat. Turning sign-in off retains its tables and clients.

Use the [installed CLI sign-in commands](cli-browser-login.md) with that server
address and a private profile. This enables account access only. The protected
coding listener still requires its separate installation; this chart setting
does not deploy it or complete the release integration.

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
The database backup does not include provider-key files, gateway registrations,
mounted credentials or certificates. Recover those separately before admitting
model calls. A restore also returns accounts, sessions and policy to the backup's
state; review later account revocations and approval changes before reopening
access. The database fixture does not prove a complete deployment recovery.
Production backup scheduling, retention, database availability, volume semantics
and review-preview cutover remain release work.

## Install the chart against an operated database

Use [the example values](../../deploy/postgres/values.example.yaml). Set
`app.image` to your packaged PostgreSQL image's registry reference and immutable
manifest digest, such as `registry.example.test/keeplane@sha256:<64 hex characters>`.
Use the digest reported by your registry after publishing the image; the local
Docker image ID is not the registry manifest digest. Helm refuses tags in
PostgreSQL mode. App copies, migration Jobs and supplied-gateway preflight use
that same image. With the managed gateway, `agentgateway-standalone.image` must
also be a `repository@sha256:<digest>` reference; the chart default already is.
Make both images available from the customer's internal registry before
closing install-time registry access. Local SQLite trials can still use tags.

Provision a private database owned by a migration role and a separate app login. Neither
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

`app.replicaCount` may exceed one in PostgreSQL mode. `/health/ready` returns 503
when the database is unavailable or a migration known to this app is pending.
Run the migration Job before admitting the new app copies. The probe only reads
migration history; it never changes the schema. Extra migrations from a newer
app version do not make an old worker unready. `/health/app` keeps the process
alive for recovery, so database failure does not trigger a liveness restart.
SQLite trial mode requires one copy and cannot be combined with PostgreSQL.

Supply an existing provider-key PVC. Multiple nodes need a volume that supports
the required shared reads/writes; the single-node test's RWO claim does not prove
that production property. Managed gateways need their read-only mount configured
separately. Customer-gateway provider credentials remain a separate integration
contract. This chart does not install or operate PostgreSQL, choose a database
operator, schedule backups or claim a release-ready gateway policy boundary.

Before each app starts, a provider-only init container restores UID 65532,
directory mode 0700 and managed key-file mode 0600. Existing paths and key bytes
stay unchanged. It runs as UID 0 with only CHOWN, FOWNER and DAC_OVERRIDE, without
privileged mode or account/database Secret mounts. Restricted Pod Security needs
an explicit exception. Leave `fsGroup` unset on every gateway sharing this PVC;
the app retains it for account storage. Volume permission repair is not a
zero-interruption guarantee for other serving copies during an app rollout.
For an existing release, [save its explicit user settings and upgrade with
`--reset-values`](kubernetes-local.md#preserve-settings-when-upgrading-helm).
Use your deployment's kubeconfig, release and namespace, and add the new
`app.image` digest as an override after the saved values. Keep the export private
and outside Git; it preserves Helm settings, not database or key backups.
