# Keep and export Audit records

This guide is for whoever installed Keeplane. It says where the Open Source
edition keeps Audit records, how long they stay, what upgrades and restores do
to them, how much space they take, and how to export them. For what each
record says, see [Audit in the local preview](audit-local.md). For how the
app writes and finds them, see the
[Audit storage design](../architecture/audit-storage.md).

## Where records are kept

Audit records are rows in the app database, next to accounts, sessions and
policy. There is no separate Audit file, cache or service.

| Installation | App database |
| --- | --- |
| Docker preview | SQLite file `/state/database/keeplane.sqlite3` in the `account-data` volume |
| Kubernetes SQLite trial | SQLite file `/state/keeplane.sqlite3` on the app's state volume |
| Kubernetes with PostgreSQL (`KEEPLANE_DATABASE_HOST` set) | The database named in `app.postgres.database` |

Two tables hold Audit data:

- `accounts_auditrecord` holds the records, one row each: `id` (the record
  number, newest highest), `kind`, `happened_at` (UTC), `actor_id`,
  `actor_name` and `description`. `kind` is one of `settings`,
  `held_requests`, `model_answers` and `break_glass_sign_ins`.
- `accounts_auditoption` holds the on or off switch for each optional kind.

The tables keep the `accounts_` prefix from before Audit had its own app
module; nothing else uses them. Every app copy reads and writes the same rows,
so all copies show the same records.

A record holds only those six columns. It never holds a prompt, an answer or
other request text, what personal-data detection found, a password, a session
or CLI token, a gateway credential or a provider key. A held-back request is
identified by a random reference (`HR-` and 12 hex digits) that isn't derived
from the request ([ADR 025](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0025-held-request-audit-content.md)).
Records do hold usernames, project names, model names and data-class names, so
treat the database and any export as private.

## How long records stay

Records stay until you remove the database itself (for example by deleting the
preview's volume or dropping the PostgreSQL database):

- Keeplane never deletes or changes a record. The Audit API only lists records
  and turns the optional kinds on or off; there is no delete action.
- Removing a user keeps their records. A record stores the account ID and the
  username as text, not a link to the account.
- Turning a kind off stops new records of that kind. Its earlier records stay
  and are still listed.
- There is no retention period and nothing removes old records automatically.
  Retention rules and sending records to another system are not part of the
  Open Source edition.

Keeplane has no way to remove some records and keep the rest. If you must keep
records for a set time only, export them as below and keep the export under
your own retention rules; the database keeps growing until it is removed.

## Upgrades

An upgrade runs Keeplane's migrations once, before the new app copies serve:
the `app-migrate` service in the Docker preview, the `migrate-local-database`
init container in the Kubernetes SQLite trial, and the `<release>-accounts-migrate`
Job in PostgreSQL mode ([PostgreSQL](postgres-accounts.md#install-the-chart-against-an-operated-database)).
No migration deletes, rewrites or copies Audit rows. Records written before an
upgrade are listed, searched and paged after it like new ones.

Before the first release there is one exception: a preview that moved its
database to a new place starts a fresh database there and doesn't import the
earlier one, Audit records included. The earlier files are left unchanged
([earlier preview data](local-preview.md#earlier-preview-data)).

## Backups and restores

Audit records are in the app database, so the app database backup in
[Back up and restore](backup-and-restore.md) includes them. `verify_restore`
reports how many there are and the newest record's time under
`audit_records`, so you can compare a restore with the backup's report.

A restore returns Audit to the moment of the backup. Records written after
that backup are not in the restored database
([after restoring an older backup](backup-and-restore.md#after-restoring-an-older-backup)).
If you must keep them, [export the records](#export-records) from the current
database before you restore, or keep that database.

## How much space records take

In SQLite a typical record, such as a model answer, takes under 300 bytes,
its index included, so a million records take under 300 megabytes.
PostgreSQL stores more per row; measure it there as shown below. Model answers
grow fastest: one coding task usually writes several records while that kind
is on.

To see how many records there are and the newest one's time, save a
`verify_restore` report. Run the Docker commands in this guide from the
repository root. The Kubernetes commands need `NS` and `RELEASE` set as in the
[backup guide's prerequisites](backup-and-restore.md#prerequisites) and the
[operations Role](kubernetes-namespace-permissions.md#operations-role).

```sh
# Docker preview
docker compose exec -T app python manage.py verify_restore > audit-report.json
# Kubernetes
kubectl -n "$NS" exec deploy/"$RELEASE"-app -c app -- \
  python /app/manage.py verify_restore > audit-report.json
```

In PostgreSQL mode, your database administrator can also see the table's size
on disk:

```sql
SELECT pg_size_pretty(pg_total_relation_size('accounts_auditrecord'));
```

## Export records

Export reads the records and leaves them in place. Keeplane's app image
includes Django's `dumpdata`, which writes every record as JSON, oldest first,
with its time in UTC:

```sh
# Docker preview
docker compose exec -T app python manage.py dumpdata audit.AuditRecord --indent 1 > audit-records.json
# Kubernetes
kubectl -n "$NS" exec deploy/"$RELEASE"-app -c app -- \
  python /app/manage.py dumpdata audit.AuditRecord --indent 1 > audit-records.json
```

Expected result: the command exits 0 and `audit-records.json` lists one entry
per record, each with `kind`, `happened_at`, `actor_id`, `actor_name` and
`description`. It can run while Keeplane serves; records written during the
export may or may not be included.

In PostgreSQL mode you can export CSV with `psql` instead, using the same
connection settings as `pg_dump` in [the backup guide](backup-and-restore.md#2-back-up-the-app-database):

```sh
PGSSLMODE=verify-full PGSSLROOTCERT=database-ca.crt \
psql --host <database host> --username keeplane_migrate --dbname keeplane \
  -c "\copy (SELECT id, kind, happened_at, actor_id, actor_name, description FROM accounts_auditrecord ORDER BY id) TO 'audit-records.csv' WITH (FORMAT csv, HEADER)"
```

Store exports like backups: they contain usernames and the names of projects,
models and data classes.

## What is tested

The [Audit storage guide cases](../../tests/integration/audit-storage-guide-cases.md)
check this guide's table, column, kind, path, migration step and command
names against the code, check that no Audit API route, app code or migration
deletes or rewrites records, run the export against a database with records
in it, and measure a record's size in SQLite. The
[persistence cases](../../tests/integration/audit-persistence-cases.md) show
records across app copies, restarts and an upgrade, and the
[backup and restore cases](../../tests/integration/backup-restore-cases.md)
check records after a restore. The `kubectl`, `docker compose` and `psql`
wrappers and PostgreSQL's row size are not run by these cases.
