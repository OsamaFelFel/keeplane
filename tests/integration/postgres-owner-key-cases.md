# Provider-key lifecycle on PostgreSQL

These run inside the disposable [PostgreSQL account fixture](postgres-accounts-cases.md),
using the actual internal store and account-removal service. The probe reads
fixture credentials before dropping to app UID 65532; every key operation runs
under that UID. Separate worker connections use one local key directory.

| Case | Check |
| --- | --- |
| PGKEY-01 | Two owners add keys. Replacing one preserves the other, leaves two 0600 files in a 0700 directory, and keeps validated bindings after reconnecting. |
| PGKEY-02 | Hold the first writer's owner lock. Observe PostgreSQL reporting the second writer waiting on a lock, then release it. Both replacements complete with one current file and no pending cleanup. |
| PGKEY-03 | Roll back account removal. Its account, session, key reference and file remain; no cleanup journal survives. |
| PGKEY-04 | Force file cleanup to fail after account removal. Its session is withdrawn and the journal survives reconnecting. The management command retries it without touching the other owner's key. |

Run `pytest tests/integration/test_postgres_accounts.py -m live --app-image keeplane-preview:postgres-local`
after preparing the image in [Testing](../../docs/guide/regression-local.md).
The fixture removes its users, model, key files and journal rows. Reports stay
outside Git. Provider validation is synthetic: this checks PostgreSQL transactions,
locks and file lifecycle, not provider acceptance, protected dispatch, independent
replica filesystems or production database permissions.
