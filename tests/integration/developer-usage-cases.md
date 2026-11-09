# Developer usage on the server

Spec 009 ST31 (D186, D191), ADR 029, task 009-08. Journey case DEV-04 (with
009-09 and 009-10). Run
`.venv/bin/python -m pytest tests/integration/test_developer_usage.py tests/integration/test_developer_usage_storage.py`.
The storage cases run once on SQLite and once on PostgreSQL; the PostgreSQL
runs need `KEEPLANE_TEST_POSTGRES_*` (CI's PostgreSQL job sets them) and are
skipped elsewhere. DU-15 needs the separately pinned CLI sign-in packages.

## On the test database (`test_developer_usage.py`)

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DU-01 | A developer reports two turns in this hour and one two hours ago, then reads their usage. | The two reports in the same hour are one total. Today and this month show 2,000 input and 500 output tokens over 7 requests, 1 of which reported no tokens. The answer is not cached. |
| DU-02 | Two developers report; each reads, and one asks for the other's usage by account ID. | Each sees only their own totals. A request with any parameter other than the time zone is refused. |
| DU-03 | A report names another developer's account ID. | The ID is ignored: the total belongs to the signed-in developer, and the other developer sees nothing. |
| DU-04 | An admin reads usage; the app's routes are listed. | The admin sees only their own (empty) usage. The only usage route is the developer's own `api/runtime/usage`; no admin route reads totals. |
| DU-05 | A report names a model that isn't approved for the project, a model that isn't set up, an unknown project or a malformed project ID. | Each is refused with 403 and nothing is recorded. |
| DU-06 | The gateway's model list can't be read. | The report is refused with 503 and nothing is recorded. |
| DU-07 | A report or a read is sent with only a session cookie, client account or role headers, a Basic header or an invalid bearer. | Each gets 401 with a Bearer challenge and nothing is recorded. |
| DU-08 | A report also carries a prompt, an answer, a file path, a repository and a project name. | The total holds only the account, model, hour and four counts; none of the extra text is stored or returned. |
| DU-09 | A report has negative, fractional, text or true/false counts, zero requests, or a missing, empty or too-long model. | Each is refused with 400 and nothing is recorded. |
| DU-10 | A report has huge numbers, or more requests without tokens than requests. | Requests are capped at 10,000, requests without tokens at the request count, and tokens at 10 million per request that reported tokens. An hourly total never passes 10^15. |
| DU-11 | Totals at hours either side of local midnight are read in UTC, New York and Tokyo. | Today and this month follow each zone's own midnight and first of the month. |
| DU-12 | Usage is read with no time zone, or with an unknown or path-like zone. | No zone means UTC. Unknown or path-like zones are refused with 400. |
| DU-13 | Totals from two months ago exist, including one that is already the previous month at UTC+14; then a report is sent, and later a read. | Totals older than the previous calendar month (in the zone furthest ahead of UTC) are deleted on each report and each read; the previous month is kept whole for every zone. |
| DU-14 | A developer's account is removed. | Their totals are removed with it. |
| DU-15 | A developer signed in through the CLI's OAuth sign-in reports and reads. | The same bearer sign-in works; the total is theirs alone. |

## Separate app processes on SQLite and PostgreSQL (`test_developer_usage_storage.py`)

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DU-S1 | Two developers report and read. | Only the signed-in developer's totals come back. |
| DU-S2 | A report names another account ID. | The stored total belongs to the signed-in developer. |
| DU-S3 | A report names a model the project doesn't allow, or an unknown project. | It is refused and nothing is stored. |
| DU-S4 | A read and a report are sent with session cookies only. | Both get 401 and nothing is stored. |
| DU-S5 | A report carries a prompt, answer and path. | The stored row holds only the account, model, hour and four counts. |
| DU-S6 | Two app copies on the same database each send 20 reports at the same time, after a total from before the previous month was written. | All 40 reports are counted in one total per hour, and the old total is gone. |
