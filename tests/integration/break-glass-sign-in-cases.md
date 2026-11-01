# Break-glass sign-in records

**Edition:** Open Source. These cases cover Spec 006 ST21 "After install" and
"Break-glass sign-ins" for task 006-01: first use, repeated use, restart,
rotation, a wrong password and a storage outage.
[`test_break_glass_sign_ins.py`](test_break_glass_sign_ins.py) signs in
through Keeplane's real sign-in API (`POST /api/session`) and reads the Audit
API, in separate control-plane processes on one fresh database. Each case runs
on a temporary SQLite file and, when configured, on PostgreSQL. No case
reports a password or a session token.

| Case | Given | Expected result |
| --- | --- | --- |
| BGS-01 First sign-in after install | A fresh install with no records. The break-glass admin signs in, opens Audit, then tries to turn break-glass recording off | Sign-in works. Settings changes, held-back requests and model answers are off, and break-glass sign-ins have no switch. One record names `first-admin`, says "Break-glass admin signed in." and gives a UTC time from the moment of sign-in. Turning it off is refused (400), and the next sign-in is recorded too. |
| BGS-02 Repeated sign-ins | Two app processes. The break-glass admin signs in three times across them; then another admin signs in | Three separate sessions, each still working, and three break-glass records, newest first, seen the same way by both processes. The other admin's sign-in adds no break-glass record. |
| BGS-03 Wrong password | The break-glass admin tries a wrong password, the right one in capitals, and the right one with a trailing space; then the right one with the username in mixed case | Each wrong attempt returns 401 with no session cookie; no session and no record exist. The last sign-in works and its record names `first-admin`. |
| BGS-04 Restart | The break-glass admin signs in twice; the process stops and a new one starts with the same mounted password | The earlier session still works, the two records are unchanged, and signing in again adds exactly one record. |
| BGS-05 Rotation | The break-glass admin signs in; the process stops; a new password is mounted and a new process starts | The old password and the old session are refused, and the refused attempt adds no record. The new password works and adds one record; the earlier record stays. Users still shows one first admin. |
| BGS-06 Storage outage | The database refuses new Audit rows, then (separately) new session rows, from two app processes | Every sign-in returns 503 "Account storage is unavailable" with no session cookie, and neither a session nor a record is kept, in either direction. Once storage is repaired, sign-in works and adds one record. No record holds the password or any session token. |

The outage is made in the database itself: a trigger fails every insert into
that table (PostgreSQL reports a full disk, SQLite a missing table). The
[isolated store cases](../e2e/audit-cases.md#always-on-break-glass-sign-ins)
BG-01 to BG-06 check the same transaction with a patched write.

Run on SQLite:

```sh
.venv/bin/python -m pytest tests/integration/test_break_glass_sign_ins.py
```

To run them on PostgreSQL as well, set the `KEEPLANE_TEST_POSTGRES_*`
variables described in the [persistence cases](audit-persistence-cases.md).
Without them the PostgreSQL cases are skipped and reported as skipped. The CI
`postgres` job sets them.

Not proven here: the production identity store chosen under 003-03, database
failover and Kubernetes replicas.
