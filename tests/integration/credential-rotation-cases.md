# Rotating installation credentials

These cases cover task 002-02 (Spec 002 ST3–ST5): rotating Keeplane's own
installation credentials on Kubernetes without losing registered models,
Keeplane's model approvals or unrelated customer models in the gateway. The
steps an installer follows are in
[database credentials and the signing secret](../../docs/guide/postgres-accounts.md#rotate-database-credentials-and-the-signing-secret)
and [gateway keys](../../docs/guide/gateway-configuration.md#rotate-the-gateway-keys).
Developers' own provider keys and TLS ingress certificates are outside these
cases.

CR-01 to CR-06 run separate control-plane processes, as pods do, and change
their mounted credential files underneath them the way Kubernetes updates a
mounted Secret. The gateway copies are small in-process stand-ins that check
key hashes like the chart's two strict key policies and share one model store
holding a Keeplane-added model and a customer's model. CR-01 to CR-03 run on
SQLite and, in CI, on PostgreSQL. CR-04 to CR-06 need PostgreSQL role
passwords and run only in CI's PostgreSQL job (or locally with
`KEEPLANE_TEST_POSTGRES_*`). CR-07 to CR-09 render the chart with Helm and are
skipped where Helm is missing. CR-U1 to CR-U6 are unit cases.

| Case | Given | Expected result |
| --- | --- | --- |
| CR-01 Gateway keys rotate | An app process with two approved models (one Keeplane-added, one the customer's) and two gateway copies. New runtime and admin keys are written to the mounted files and both copies restart with the new hashes | Without restarting the app, its next management and model calls are accepted. `check_credentials` passes before and after, with the same gateway model list (both models, same fingerprints) and the same approvals. The gateway's model store is unchanged and the old keys open nothing. |
| CR-02 Half-done gateway rotation | As CR-01, but only the second copy has restarted | The gateway status API answers 503 "The gateway refused Keeplane's admin key…", never the gateway's 401, and the app logs it. `check_credentials` exits 1 and shows which copy refuses both keys; its output holds no key or key hash. Once the first copy restarts the check passes and approvals are unchanged. |
| CR-03 Signing secret rotates | The first admin is signed in. The process restarts with the same secret, then with a new one | A restart alone keeps the session. After the new secret the old session is refused, the first admin can sign in again, and approvals, classes, accounts and Audit records are unchanged. A running process keeps the secret it started with. |
| CR-04 Database password, documented order | A running app process connected as its own PostgreSQL role. The Secret file gets the new password first; then the role's password is changed | Every request succeeds throughout. While the role still has the old password the process keeps using it, logs once that the mounted one is refused, and `check_credentials` exits 1 saying so; a new process reports the database as refused. After the role changes, the same process uses the new password at once, the old one is refused by the server, the check passes and a new process starts. No log line holds either password. Approvals and settings are unchanged. |
| CR-05 Role changed before the Secret | The role's password is changed first, then the file | Requests fail while they differ, then succeed as soon as the file changes, without a restart. |
| CR-06 Wrong password in the Secret | A mistyped password is written to the file and the role is not changed | The process keeps working on the accepted password, logs the refusal once, and the check exits 1. Writing the right password back clears it. |
| CR-07 App credentials come from Secret files | The chart rendered for PostgreSQL in managed and customer-run modes | The app reads the database password, database CA, signing secret, first-admin password and both gateway keys only as files from read-only Secret volumes named in the values, with no `subPath` (which would never receive an update) and no credential in an environment value. The migration Secret never reaches the app. |
| CR-08 Migration Job credentials | The same renders | The pre-install/pre-upgrade Job mounts the migration role's Secret and the CA Secret, never the app's password, so each Helm run reads the current ones. |
| CR-09 Managed gateway key hashes | The managed render | Each gateway copy loads both key hashes from the keys Secret as environment variables read at start, with no `subPath`, and each key policy holds the single hash variable: a key change needs the copies restarted. |
| CR-U1 Password read per connection | A password file changes after a connection | The next connection uses the new password; nothing else is tried. |
| CR-U2 Documented order | The file changes, then the role | No connection fails; the database sees one refused try per process; exactly two log lines, neither holding a password. |
| CR-U3 Unaccepted passwords | A wrong, empty or missing file | A wrong password fails the connection; an empty or missing file fails before any connection is tried. |
| CR-U4 Refused gateway key | The gateway answers 401 to the admin key | The app answers 503 with the plain message and logs it; other gateway failures pass through unchanged. |
| CR-U5 Public gateway health | The gateway answers 403 | `/health` answers 503 `{"gateway": "unavailable"}` and says nothing more. |
| CR-U6 Key check outcomes | Gateway answers 200, 401, 403, an unreadable key file, or unavailable | Reported as accepted, refused, refused, unreadable and unreachable. |

Not proven here: a live Kubernetes rotation (kubelet's Secret refresh delay,
a real gateway image restarting, requests in flight across a rollout) and a
TLS server switching to a certificate from a new CA. The CA file is passed to
libpq as a path, which libpq reads for each new connection; the existing chart
fixture proves verified TLS and refusal of a wrong CA.

Run on SQLite (chart cases skip without Helm):

```sh
.venv/bin/python -m pytest tests/integration/test_credential_rotation.py tests/unit/test_credential_rotation_checks.py
```

Run the PostgreSQL cases against a disposable server whose user may create
roles and databases:

```sh
KEEPLANE_TEST_POSTGRES_HOST=127.0.0.1 KEEPLANE_TEST_POSTGRES_PORT=5432 \
KEEPLANE_TEST_POSTGRES_USER=keeplane KEEPLANE_TEST_POSTGRES_PASSWORD_FILE=/private/path \
.venv/bin/python -m pytest tests/integration/test_credential_rotation.py -k postgresql
```
