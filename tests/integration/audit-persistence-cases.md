# Finding persisted Audit records

These cases cover spec 006 ST22 ("Find records") against the stored records,
not an in-memory test database. Each case starts separate control-plane
processes with their own database connections on one fresh database. Records
include always-on break-glass sign-ins, written through the real sign-in path.

| Case | Given | Expected result |
| --- | --- | --- |
| AS-01 Two app processes | Process A writes 30 settings records; process B signs in three times as the break-glass admin | Both processes see the same 33 records, newest first: 25 on page 1, 8 on page 2, and an empty page past the end. Showing break-glass sign-ins lists only the 3 sign-ins. Searching "rule 2" lists only the 10 matching changes. Searching for "Break-glass" under settings changes finds nothing. Search ignores letter case. |
| AS-02 Restart | Both processes from AS-01 stop and a new one starts | The new process sees exactly the same pages, kinds and search results. |
| AS-03 Upgrade | 27 settings records and one break-glass sign-in were written under the schema before the Audit app split; the database is then upgraded and the admin signs in again | All 29 records remain. The new sign-in is listed first; Show finds both sign-ins; searching "legacy routing" pages through all 27 earlier changes with their UTC times. |

Each case runs on a temporary SQLite file. To run it on PostgreSQL as well,
point the test at a disposable server whose user may create databases. The test
creates and then drops its own uniquely named database.

```sh
.venv/bin/pip install psycopg==3.3.6
KEEPLANE_TEST_POSTGRES_HOST=127.0.0.1 KEEPLANE_TEST_POSTGRES_PORT=5432 \
KEEPLANE_TEST_POSTGRES_USER=keeplane \
KEEPLANE_TEST_POSTGRES_PASSWORD_FILE=/path/to/password \
.venv/bin/python -m pytest tests/integration/test_audit_persistence.py
```

`KEEPLANE_TEST_POSTGRES_NAME` (default `postgres`) names the database used to
create the test database. `KEEPLANE_TEST_POSTGRES_SSLMODE` defaults to
`disable` for a local disposable server. Without these settings the PostgreSQL
cases are skipped and reported as skipped.

These cases do not prove database failover, backup scheduling, Kubernetes
replicas or the Audit screen; see the [browser cases](../browser/audit-cases.md).
