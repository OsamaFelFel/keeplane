# Shared PostgreSQL accounts and settings

**Edition:** Open Source; Enterprise uses the same base identity and storage contract.

Keeplane can run its existing API against PostgreSQL. UUID accounts, native
Django sessions, sign-in budgets, account operation IDs, Editions preferences,
model approvals, data classes and Audit records share one database. The Docker
and kind review previews still use SQLite. The release chart and supported
database operations remain in progress.

## Configure a clean installation

Install the pinned API requirements and
`components/control-plane/requirements-postgres.txt`. The latter uses the
replaceable pure-Python Psycopg 3.3.6 distribution and needs an installed `libpq`.
The default preview image does not yet include that optional driver or select
a production native-library distribution. Keep the LGPL notice and corresponding
source available, and record the exact native libraries and notices when
packaging it. Binary wheels bundle additional native dependencies; their package
license alone is insufficient inventory. See the [Psycopg installation choices](https://www.psycopg.org/psycopg3/docs/basic/install.html).

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
key. The isolated HTTP fixture disables database TLS; that is not production TLS
evidence.

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
Production backup scheduling, retention, restricted database roles, Kubernetes
storage, database TLS and deployment cutover remain release work.
