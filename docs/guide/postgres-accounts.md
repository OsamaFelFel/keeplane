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
replicas that may restart. In the chart, follow
[rotate the first-admin password](#rotate-the-first-admin-password).

To back up and restore this database, follow
[Back up and restore](backup-and-restore.md). Back up the database with
`pg_dump` as the migration role, together with the provider-key folder and the
gateway's database, and keep the signing secret in your secret store. Restore
into a fresh database, point all replicas at it and run
`python /app/manage.py verify_restore` before reopening access. The database
backup does not include provider-key files, gateway registrations, mounted
credentials or certificates. A restore also returns accounts, sessions and
policy to the backup's state, including access withdrawn since; the guide says
what to recheck. Backup scheduling, retention and database availability belong
to your database operator.

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
| `gateway.keysSecret` | `runtime-key` and separate `admin-key`; with the managed gateway also their hashes, as in [gateway access keys](kubernetes-installation-reference.md#gateway-access-keys) |

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

## Rotate database credentials and the signing secret

Each credential stays in the Secret you created; rotating one changes that
Secret's contents in place and keeps its name, so no values change and no Helm
upgrade is needed. Model approvals, data classes, accounts, Audit records and
the gateway's registered models (Keeplane's and your own) are not touched by
any of these steps. Gateway keys are covered in
[rotate the gateway keys](gateway-configuration.md#rotate-the-gateway-keys).

| Credential | Secret and key | Read by | When a change takes effect |
| --- | --- | --- | --- |
| App role password | `app.postgres.credentialsSecret`, `password` | Every app copy | On the next database connection (each request opens one), no restart |
| Migration role password | `app.postgres.migration.credentialsSecret`, `password` | The pre-install/pre-upgrade Job only | On the next Helm install or upgrade |
| Database CA | `app.postgres.caSecret`, `ca.crt` | App copies and the migration Job | On the next database connection, no restart |
| Signing secret | `app.postgres.identitySecret`, `signing-secret` | App copies at start; the migration Job | After the app copies restart |
| First-admin password | `app.postgres.identitySecret`, `first-admin-password` | App copies at start | After the app copies restart |

Kubernetes refreshes a mounted Secret file in each pod on its own schedule,
usually within a minute or two. The chart mounts every credential without
`subPath`, so the refresh always reaches the pods
([CR-07](../../tests/integration/credential-rotation-cases.md)).

### Before and after every rotation

Set your namespace and release once, then save what Keeplane can see:

```sh
NS=<namespace>; RELEASE=<release>
kubectl -n "$NS" exec deploy/"$RELEASE"-app -c app -- \
  python /app/manage.py check_credentials > before.json
```

`check_credentials` prints one JSON report and exits 1 if anything is refused.
It shows whether the database accepts the app's password and whether every
gateway copy accepts the admin and runtime keys, and it lists the registered
gateway models (with their definition fingerprints) and Keeplane's approvals.
It never prints a password, key or key hash. It also lists the database CA and
the database server's certificate with their expiry dates, and fails if one has
expired; see [check and renew certificates](certificate-operations.md).
Start only when `"passed": true`.
Its `"database"` line is one of:

| `"database"` | Meaning |
| --- | --- |
| `connected` | The database accepts the password in the mounted file. |
| `the database refuses the mounted password` | The server was reached and refused the login: the role's password differs from the Secret, or the role or `pg_hba.conf` doesn't allow it. |
| `unreachable` | No answer from the server: network, DNS, TLS verification or the server being down. |

The check runs in a new process inside the pod, not in the serving process,
so it only ever knows the password in the file. It never reports what the
serving copies are using; their log shows that (below). If your server sends
its messages in a language other than English (`lc_messages`), a refused login
shows as `unreachable`.
After the rotation, save `after.json` the same way and compare:

```sh
diff <(jq '{gateway_models, approvals}' before.json) \
     <(jq '{gateway_models, approvals}' after.json) && echo unchanged
```

To see which copies already read a new file, compare its SHA-256 in each app
pod with your local file (the app ignores a trailing newline):

```sh
mounted_sha() {
  kubectl -n "$NS" exec "$1" -c app -- python -c \
    'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read().strip()).hexdigest())' "$2"
}
for pod in $(kubectl -n "$NS" get pods -l app="$RELEASE"-app -o name); do
  echo "$pod $(mounted_sha "$pod" /run/keeplane-database/password)"
done
tr -d '\n' < app-db-password | shasum -a 256
```

Keep new credential files with `umask 077` and delete them, or move them to
where your other installation secrets live, when you finish.

### Rotate the app role's password

PostgreSQL keeps one password per role, so change the Secret first and the
role second. While the role still has the old password, each app copy keeps
using the last password the database accepted and logs once: "The database
refused the password in the mounted file; still using the previous password."
As soon as the role changes, the copies switch on their next connection and log
"The database accepted the password in the mounted file." No request is
refused along the way ([CR-04](../../tests/integration/credential-rotation-cases.md)).

1. Make the new password and put it in the Secret:

   ```sh
   umask 077
   openssl rand -hex 32 | tr -d '\n' > app-db-password
   printf '{"data":{"password":"%s"}}' "$(base64 < app-db-password | tr -d '\n')" > app-db-patch.json
   kubectl -n "$NS" patch secret <app-credentials-secret> --type merge --patch-file app-db-patch.json
   ```

2. Wait until every app pod shows the new file's SHA-256 (above), or until each
   pod has logged "still using the previous password". That line means the
   copy has the new file and is still serving with the old password. The
   readiness probe opens a connection every 5 seconds, so it appears soon
   after the file arrives:

   ```sh
   kubectl -n "$NS" logs -l app="$RELEASE"-app -c app --since=10m --prefix | grep 'previous password'
   ```

   From now until step 3, `check_credentials` reports `"database": "the
   database refuses the mounted password"` and `"passed": false`. That is
   expected: the role still has the old password. The pods stay ready and
   requests keep succeeding; `kubectl -n "$NS" get pods -l app="$RELEASE"-app`
   shows them all `1/1 Running`. If the check says `unreachable` instead, stop:
   that is a network or TLS problem, not this rotation.

3. Change the role's password. psql's `\password` asks for it and sends only a
   SCRAM hash, so the password stays out of shell history and server logs.
   Paste the contents of `app-db-password`:

   ```sh
   psql "host=<db-host> dbname=<database> user=<admin-role> sslmode=verify-full" \
     -c '\password <app-role>'
   ```

4. Within a few seconds each pod logs "accepted the password in the mounted
   file". `check_credentials` now reports `"database": "connected"`. Save
   `after.json`: `"passed": true`, and the models and approvals unchanged.

Don't restart or scale the app between steps 1 and 3: a copy that starts in
that window has only the new password, can't start, and Kubernetes restarts it
until step 3. It takes no traffic meanwhile. Keep the window short.

If something goes wrong:

- **The role was changed before the Secret.** Copies can't connect, report
  storage as unavailable and turn unready until the new file reaches them.
  Finish step 1 at once; they recover on their own, without a restart
  ([CR-05](../../tests/integration/credential-rotation-cases.md)).
- **The Secret holds a wrong password.** From the outside this looks the same
  as the expected state between steps 1 and 3: the copies keep serving with
  the previous password and log "still using the previous password", and
  `check_credentials` reports "the database refuses the mounted password". So
  before step 3, check that the pods' SHA-256 matches your `app-db-password`
  file. If it doesn't, write the right password to the Secret. If you already
  ran step 3 with a different value, the copies can't connect: put the
  password you set on the role into the Secret, and they recover without a
  restart ([CR-06](../../tests/integration/credential-rotation-cases.md)).
- **A pod never shows the new file.** Restart the app copies with
  `kubectl -n "$NS" rollout restart deployment/"$RELEASE"-app`, after step 3.
- **To back out before step 3**, put the old password back in the Secret.

### Rotate the migration role's password

Only the migration Job uses it, at each Helm install or upgrade; app copies
never read it. Put the new password in
`app.postgres.migration.credentialsSecret` with the same commands as step 1
above (file `migration-db-password`), then change the migration role's password
with `\password <migration-role>`. Don't run a Helm upgrade between the two.
The next `helm upgrade` runs the Job with the new password. If the Job can't
connect, Helm stops before changing the app; correct the Secret or the role and
run the upgrade again. If `app.postgres.migration.enabled=false`, give the new
password to your own migration process instead.

### Rotate the database CA

libpq reads the CA file for each new connection, so the app picks up a new CA
without a restart. Trust both CAs while the server's certificate changes:

1. Put a bundle of the old and new CA certificates in the Secret:

   ```sh
   cat old-ca.crt new-ca.crt > ca-bundle.crt
   printf '{"data":{"ca.crt":"%s"}}' "$(base64 < ca-bundle.crt | tr -d '\n')" > ca-patch.json
   kubectl -n "$NS" patch secret <ca-secret> --type merge --patch-file ca-patch.json
   ```

2. Wait until every app pod reads the bundle: `mounted_sha <pod>
   /run/keeplane-database-ca/ca.crt` matches `tr -d '\n' < ca-bundle.crt |
   shasum -a 256` for each pod.
3. Have your database operator switch the server to its certificate from the
   new CA. Its name must still match `app.postgres.host`; the chart always
   uses `verify-full`.
4. Save `after.json`: `"database": "connected"`. All app pods stay ready.
5. Put only `new-ca.crt` in the Secret the same way, wait for every pod as in
   step 2, and check again.

`check_credentials` lists every CA in the file under
`certificates.database_ca`, with its fingerprint and expiry date, so you can
see which CAs the pods trust at each step.

If the server switched before a pod read the bundle, that pod's new
connections fail verification and `/health/ready` answers 503, so it takes no
traffic. Finish step 1 or switch the server back; the pod recovers without a
restart. The next migration Job reads the CA current at that time.

### Rotate the signing secret

The signing secret protects browser sessions and CLI sign-ins. Changing it
signs everyone out: the next request asks people to sign in again, and CLI
users run their sign-in again. Accounts, the first-admin password, model
approvals, data classes and Audit records stay as they were
([CR-03](../../tests/integration/credential-rotation-cases.md)). App copies
read it only at start, so they must restart.

1. Make a new secret (at least 48 characters) and put it in the identity
   Secret, leaving `first-admin-password` as it is:

   ```sh
   umask 077
   openssl rand -hex 32 | tr -d '\n' > signing-secret
   printf '{"data":{"signing-secret":"%s"}}' "$(base64 < signing-secret | tr -d '\n')" > identity-patch.json
   kubectl -n "$NS" patch secret <identity-secret> --type merge --patch-file identity-patch.json
   ```

2. Restart the app copies and wait:

   ```sh
   kubectl -n "$NS" rollout restart deployment/"$RELEASE"-app
   kubectl -n "$NS" rollout status deployment/"$RELEASE"-app
   ```

   During the rollout a session made on a new copy isn't valid on an old one,
   so someone may be asked to sign in twice. A model call in progress on a copy
   that stops is cut when the copy's 30-second shutdown ends; the developer
   sends it again.

3. Sign in as an admin and save `after.json`; the models and approvals are
   unchanged.

If new copies don't start and log "The shared signing secret must be at least
48 characters", the Secret holds a short or empty value: write a correct one;
the copies retry on their own. The old copies keep serving until new ones are
ready. Before step 2 you can still back out by putting the old secret back.

### Rotate the first-admin password

Write the new password (12–256 characters) to the identity Secret's
`first-admin-password` key the same way as the signing secret above, then
restart the app copies with the same two `rollout` commands. Every copy starts
with the new password, so they never disagree. The account keeps its UUID, its
old sessions end, and a locked sign-in budget is cleared. Sign in with the new
password to confirm.
