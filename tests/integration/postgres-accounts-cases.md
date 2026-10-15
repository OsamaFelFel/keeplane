# PostgreSQL account and settings integration cases

**Edition:** Open Source; the same base contract applies to Enterprise.

Two real Keeplane app processes share one signing secret and PostgreSQL database.
A small gateway API fixture tests model-approval coordination. These cases do
not prove runtime gateway policy, production database TLS or release packaging.
Existing previews are not reset.

| Case | Check |
| --- | --- |
| PGAPI-01 | All 21 existing account/edition cases pass on a clean migrated database, including managed-admin protection, UUID accounts, roles, paging and operation readback. |
| PGAPI-02 | All eight browser CSRF cases pass against PostgreSQL accounts. |
| PGAPI-03 | One copy creates a native session; the other authenticates the same UUID. Logout revokes access on both. |
| PGAPI-04 | Eight simultaneous creates across both copies return one UUID. Check finds it; changed-password retry conflicts. Promotion affects the existing session; demotion revokes it. |
| PGAPI-05 | Ten simultaneous mixed-case attempts across both copies permit five password checks and throttle five. Expired budgets reopen. |
| PGAPI-06 | Classes start off. Mode, class edits, model approval and Audit settings/records are shared through the API. Mandatory sign-in Audit cannot be disabled. Ask uses the approval. |
| PGAPI-07 | Force Audit inserts to fail. Sign-in returns 503 with no cookie/session row; mode, approval and class rename changes roll back with their Audit records. Remove the fixture constraint afterward. |
| PGAPI-08 | A session past its database expiry is refused by another copy. |
| PGAPI-09 | Stop PostgreSQL. Protected pages, identity and sign-in fail closed with 503; no new cookie is returned. |
| PGAPI-10 | Restart PostgreSQL with the app workers still running. The prior identity/session, settings, approval and Audit recover. |
| PGAPI-11 | Restart both apps; the same identity/session and records remain. |
| PGAPI-12 | Dump and restore into a fresh database, then recreate both apps against it. The original identity/session and records remain. |
| PGAPI-13 | Exhaust the first-admin budget, update the shared password and restart one copy. Its UUID remains; new password works; old password and sessions fail on both copies. |
| PGAPI-14 | ASCII case variants sign in and collide as duplicate names. Unicode lookalikes cannot alias an account or obtain a separate budget; the username column uses explicit C collation. |
| PGAPI-15 | An in-use class reports its project count and cannot be removed. The last class and writes while disabled are protected. Turning the mode off and on retains existing definitions. |
| PGAPI-16 | Start from the previous Django schema and populate all 12 record types. Move models into their domain apps without recreating tables; accounts, sessions, preferences, budgets, classes, approvals and Audit records remain intact. |
| PGAPI-18 | Run the [owner-key cases](postgres-owner-key-cases.md) under app UID 65532: isolate two owners, observe PostgreSQL blocking a concurrent writer, roll back account removal, and retry a persisted file-deletion journal. Provider validation is synthetic. |

Run `.venv/bin/python -m pytest tests/integration/test_postgres_accounts.py -m live`
after building `keeplane-preview:kind-local`. GitHub Actions runs this fixture
on pull requests. It downloads the matching wheels from PyPI using the committed
SHA-256 requirements. An optional `--wheels <verified-wheel-directory>` uses an
offline cache containing Psycopg 3.3.6 and its CPython 3.13 binary wheel. The
runner installs offline with hash enforcement, records source/base-image hashes,
and removes its own containers, volumes, network, temporary secret files and
derived image. It never prints credentials or cookies. Failed reports remain in
the ignored results directory or CI artifacts. Binary-wheel testing does not
select the release distribution.

Use `--app-image keeplane-preview:postgres-local` to test the source-built driver package. PGAPI-09 also requires readiness 503 and liveness 200 during database loss; recovery requires readiness 200. The default hash-verified binary-wheel fixture remains available for component comparison.
