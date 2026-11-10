# Identity across two app copies

These cases cover part of task 003-03 (ADR 012 release gate): sessions, role
changes, browser security tokens (CSRF) and the sign-in attempt limit when
Keeplane runs as two copies behind one address.
[`test_identity_replicas.py`](test_identity_replicas.py) starts two separate
control-plane processes on one fresh database with the same signing secret and
first-admin password file, as two replicas are configured. The test holds one
browser's cookies and sends each request to the copy the case names, through
Django's full request handling with CSRF checks on. Each case runs on a
temporary SQLite file and, when configured, on PostgreSQL. No case reports a
password, a session cookie or a token.

| Case | Given | Expected result |
| --- | --- | --- |
| IDR-01 A session works on both copies | The first admin signs in on copy A, then signs out on copy B | Before sign-out both copies return the same identity and copy B lists Users. Sign-out on B removes the cookie, and replaying the old cookie to either copy returns 401. No session row remains. |
| IDR-02 Role changes reach the other copy at once | An admin on A creates a developer, who signs in on B. The admin promotes them on A, then demotes them on B | Before promotion Users refuses the developer (403). After promotion their existing session opens Users on both copies. After demotion their session is refused (401) on both; the admin's session still works. |
| IDR-03 CSRF tokens are shared and checked by both copies | A browser loads the sign-in options from A, signs in on B, then changes the Editions note | The token from A signs in on B. The token from before sign-in is refused (403 `csrf_failed`) on both copies, as are another browser's token and no token; the setting is unchanged. The current token works on either copy and each copy reads the other's change; the note is restored. |
| IDR-04 Every state-changing route needs the token | The signed-in first admin sends POST, PUT, PATCH and DELETE to every route in Keeplane's URL table, on both copies, with the session and CSRF cookies and the right Origin and action header, but no token | Every browser route returns 403 `csrf_failed` before its view runs, including sign-in, sign-out, Users, roles, models, levels, persona rules, classes, projects, Audit, Editions and device confirmation. The routes without a CSRF check are exactly the reviewed list of CLI and gateway routes that take only their own bearer credential; the session cookie opens none of them (401, 403, or 503 where that credential isn't configured). Every stored row is unchanged afterwards and the session still works. |
| IDR-05 One sign-in budget across copies | Five wrong passwords for `first-admin` alternate between A and B in mixed casing; then the right password on each copy; then an unknown username on alternating copies | The five wrong attempts return 401. The right password then returns 429 with a retry delay of at most a minute on both copies, sets no session cookie, and adds no session or break-glass record; one budget row counts five attempts. The unknown username gets the same five attempts and the same 429 answer. |
| IDR-06 Success on one copy clears the other's budget | Four wrong attempts on A, then the right password on B in another casing | Sign-in works and the budget is gone, so A allows five more wrong attempts before B refuses the next with 429. |
| IDR-07 Simultaneous attempts on both copies | Ten wrong sign-ins sent at the same moment, five threads on each copy, in five casings of `first-admin` | Exactly five reach the password check (401) and five are refused (429). No session or record exists and the one budget row counts five. |

The route table in IDR-04 is read from Django in each copy, so a route added
later is checked without editing the test. A new route without a CSRF check
fails the case until it is added to the reviewed list in the test.

Run on SQLite:

```sh
.venv/bin/python -m pytest tests/integration/test_identity_replicas.py
```

To run them on PostgreSQL as well, set the `KEEPLANE_TEST_POSTGRES_*`
variables described in the [persistence cases](audit-persistence-cases.md).
Without them the PostgreSQL cases are skipped and reported as skipped. The CI
`postgres` job sets them and fails if they are skipped.

Not proven here: copies running from the release image behind a real load
balancer (the [PostgreSQL account cases](postgres-accounts-cases.md) PGAPI-02,
PGAPI-03 and PGAPI-05 cover two containers from the image), the CLI sign-in
token endpoints with CLI sign-in switched on (the
[CLI OAuth cases](cli-oauth-identity-cases.md)), Kubernetes replica failure and
database failover.
