# Backing up and restoring Keeplane's data

These cases cover task 002-02 (durable databases, backup and restore) and the
backup and restore part of 003-03 (production identity operations). The steps
an installer follows are in [Back up and restore](../../docs/guide/backup-and-restore.md).

Each step runs the real control plane in its own process with production
settings, as an app copy, a migration Job or `kubectl exec` does. The test fills
a database through Keeplane's own services, backs it up with the guide's
command (the SQLite online backup, or `pg_dump --format=custom` by the owning
role), backs up the provider-key folder with `tar`, restores both into a fresh
database and folder, runs `migrate` and then `verify_restore`. The gateway is a
small in-process stand-in that lists definitions with revisions, so approvals
are checked against definitions the way the real policy does.

The filled database holds the first admin, a second admin, a developer, their
browser sessions and a CLI sign-in; data classes turned on with the project set
to Internal; three approved models (one Keeplane-added, one the customer's, one
using developers' own keys); a developer key; and Audit records with every
optional kind turned on.

On PostgreSQL the database is owned by a migration role and the app connects as
a separate restricted role, set up as the [PostgreSQL guide](../../docs/guide/postgres-accounts.md#install-the-chart-against-an-operated-database)
asks. The restored database is created the same way, and the restore runs as
the migration role with `--no-owner`.

| Case | Given | Expected result |
| --- | --- | --- |
| BR-01 Fresh restore matches the backup | A backup restored into a new database and a new key folder, then migrated | `verify_restore` passes with no pending or unknown migrations, and every count (accounts, admins, sessions, CLI sign-ins, classes, projects, approvals, level picks, persona rules, Audit records and the newest Audit time) equals the report saved when the backup was taken. The developer key file is present and readable. |
| BR-02 Accounts and sign-ins survive | The restored database | The same accounts and roles exist; every saved browser session still opens with its role; the developer's password works; the CLI sign-in is still valid. |
| BR-03 Policy and Audit survive | The restored database | Data classes stay on with the same three classes; the project keeps Internal; every approval keeps its classes and the same models are allowed for the project. Every Audit record is there, in order, with the same text, including the model-answer record and the break-glass sign-in. |
| BR-04 Developer keys survive with their files | The restored database and key folder | The developer's key resolves to the exact value they added. |
| BR-05 An older backup undoes later withdrawals | After the backup an admin narrows one model to Confidential, removes the customer's model from Keeplane, a developer signs out and an admin account is removed; then the backup is restored | All four come back: both models are allowed for the Internal project again, the signed-out session works again and the removed admin exists again. This is why the guide says to recheck Models, Users and the gateway after restoring an older backup, or to sign everyone out. |
| BR-06 A new signing secret signs everyone out | The restored database with a different signing secret | `verify_restore` passes and reports the unexpired sessions as not usable (0). Every browser session and the CLI sign-in are refused. Accounts, passwords, approvals, allowed models and the developer key are unchanged. |
| BR-07 Missing or loose key files | The restored database with an empty key folder; and with the key files restored with mode 0644 | The developer key is refused (never another value). `verify_restore` exits 1, counts the file as missing or unreadable and says what to do. |
| BR-08 The gateway restored to a different point | The restored database, while the gateway lists the Keeplane model at a newer revision and no longer lists the customer's model | The approvals are still stored, but neither model is allowed: a restored approval never applies to a definition it wasn't made for. |
| BR-09 A backup from an older version | A backup taken one migration behind this version | Before `migrate`, `verify_restore` exits 1, names `model_registry.0008_persona_rules` as pending, says to run `migrate` and reads no records. After `migrate` it passes and the accounts, sessions and developer key are there. |
| BR-10 A backup from a newer version | The ledger holds a migration this version doesn't ship | `verify_restore` exits 1, names it, says to restore with that version or newer and reads no records. |
| BR-11 An empty database | An app copy pointed at a new, empty database | `verify_restore` exits 1 with nothing applied and every migration pending, so an empty database is never mistaken for a restore. |
| BR-12 No secrets in the report | The reports from BR-01 and BR-06 | They hold no session key, password, signing secret, provider key or key filename. |

Not proven here: the Docker preview and Kubernetes commands in the guide
(`docker compose exec`, `kubectl exec`, the chart's migration Job), which this
suite replaces with the same commands run directly; a backup of the gateway's
own database (the [gateway database cases](../e2e/gateway-secret-cases.md) cover
catalog recovery in kind); container UID 65532 ownership of key files (the
[provider-volume cases](kubernetes-provider-volume-cases.md) cover the chart's
permission repair; here files keep the test user's owner); backup
scheduling, retention and point-in-time recovery, which belong to the
database operator.

Run on SQLite:

```sh
.venv/bin/python -m pytest tests/integration/test_backup_restore.py
```

Run on PostgreSQL as well, against a disposable server whose user may create
roles and databases, with `pg_dump` and `pg_restore` at least as new as the
server (on `PATH`, under `/usr/lib/postgresql/*/bin`, or in
`KEEPLANE_TEST_POSTGRES_BIN`):

```sh
KEEPLANE_TEST_POSTGRES_HOST=127.0.0.1 KEEPLANE_TEST_POSTGRES_PORT=5432 \
KEEPLANE_TEST_POSTGRES_USER=keeplane KEEPLANE_TEST_POSTGRES_PASSWORD_FILE=/private/path \
.venv/bin/python -m pytest tests/integration/test_backup_restore.py -k postgresql
```

Each run creates and drops its own roles and databases.
