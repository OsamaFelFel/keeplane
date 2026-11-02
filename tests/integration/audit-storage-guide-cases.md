# Audit storage guide

**Edition:** Open Source. These cases keep
[Keep and export Audit records](../../docs/guide/audit-storage.md) true to how
the app stores, keeps and exports Audit records (task 006-03, Spec 006 ST22).
They read the guide as text and compare it with the Audit models, the
migrations, the URL routes, the settings, `compose.yaml` and the chart. The
export and size cases run the guide's own commands against a temporary SQLite
database in separate processes. No Docker, Kubernetes, Helm or PostgreSQL is
needed.

Run `.venv/bin/python -m pytest tests/integration/test_audit_storage_guide.py`.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ASG-01 | Compare the guide's tables, columns and record kinds with the Audit models. | The records table is `accounts_auditrecord` and the switches table `accounts_auditoption`; a record has exactly the six columns the guide names; the kinds are the four the app accepts, in order; a held-back request's reference is random (`HR-` and 12 hex digits). |
| ASG-02 | Compare the guide's database locations with the app's settings, the Docker preview and the chart. | SQLite at `/state/keeplane.sqlite3` by default and `/state/database/keeplane.sqlite3` in the preview's `account-data` volume; PostgreSQL when `KEEPLANE_DATABASE_HOST` is set, named by `app.postgres.database`. |
| ASG-03 | List every Audit API route, every file that uses the records table, and every relation to it. | Records are only read (`GET /api/audit/records`); switches are only read and set. Only the Audit store and the restore check use the table, to add, list or count rows, never to delete or change them. No model has a relation to the records, so removing a user can't remove them. |
| ASG-04 | Read every migration's database operations. | Only `accounts.0001_initial` creates the Audit tables and index; no later migration drops, alters, renames or rewrites them, and no SQL or Python migration step names them. The preview's `app-migrate` service, the trial's `migrate-local-database` init container and the `<release>-accounts-migrate` pre-install/pre-upgrade Job run `migrate`, as the guide says. |
| ASG-05 | Look up every `manage.py` command and argument in the guide. | `verify_restore` and `dumpdata` exist and their arguments parse; each Docker line runs in the preview's `app` service and has the same Kubernetes form in the app container; `verify_restore` reports `audit_records` with a total and the newest time. |
| ASG-06 | Write a break-glass sign-in, an off-kind attempt and three model answers, then run the guide's export. | The export lists the four written records in order, with their kind, UTC time, account ID, username and description, and the table is unchanged afterwards. The guide's PostgreSQL `\copy` query selects the same rows from the same table. `verify_restore` counts four records and gives the newest one's time. |
| ASG-07 | Write 5,000 model-answer records into a fresh SQLite database and compact it. | Each record takes less space than the guide's "under N bytes", and the guide's per-million figure matches it. |
| ASG-08 | Follow every link in the guide. | Each file exists and each `#anchor` is a heading in it; the Audit preview guide links to this guide and the backup guide links to its export section. |

Not proven here: the `docker compose`, `kubectl` and `psql` commands against
running containers, a cluster or a PostgreSQL server, and the size of a record
in PostgreSQL. The [persistence cases](audit-persistence-cases.md) cover records
across app copies, restarts and an upgrade on SQLite and PostgreSQL; the
[backup and restore cases](backup-restore-cases.md) cover records after a
restore.
