# PostgreSQL API and shared persistence verification

**Edition:** Open Source; Enterprise retains the same base identity contract.

The optional backend now implements the existing Keeplane APIs using one
PostgreSQL database: UUID users, native Django sessions, shared password-attempt
budgets, concurrent create-operation IDs, Editions preferences, model approvals,
data classes and Audit. Serving processes require explicit prior migrations and
a shared signing-secret file. There is no SQLite or random-secret fallback in
PostgreSQL mode. Storage failures return unavailable responses and refuse new
sessions. The review previews remain SQLite.

## Results

- [Final PostgreSQL fixture](2026-10-12-postgres-api-verified.json): **15/15
  integration groups pass**, including all 29 original account/CSRF cases,
  ASCII username rules, project-count/removal guards and atomic rollback of
  class names, model approvals and their Audit records. The fixture is removed.

- [Default-preview full regression](2026-10-12-postgres-backend-full-regression.json):
  **55/55 suites and 332/332 case records pass** against the rebuilt Docker/kind
  previews. Their SQLite and real trial gateway paths remain working.

- [Offline-cache fixture](2026-10-12-postgres-api-final.json): **13/13 integration
  groups pass**, including all **21 existing account and eight CSRF cases**.
- [CI-style download repeat](2026-10-12-postgres-api-download.json): the same
  **13/13 groups pass** with official PyPI downloads checked against committed
  SHA-256 pins, followed by offline installation with hash enforcement.
- [ASCII account comparison](2026-10-12-postgres-api-ascii.json): **14/14 groups
  pass**, adding explicit C collation, case-insensitive ASCII uniqueness/sign-in
  and rejection of Unicode lookalikes that could otherwise create a different
  password-attempt bucket. Native password checks retain Django's hash upgrade
  behavior.
- Both runs prove cross-copy sessions/logout, immediate role changes and
  revocation, eight concurrent creates returning one UUID, shared mixed-case
  attempt limits, settings/model/class/Audit writes, forced Audit rollback,
  server-side expiry, database outage/recovery with workers still running,
  app restart, fresh-database restore and infrastructure password rotation
  after exhausting the break-glass budget. Every disposable fixture is removed.
- Runtime: Django **5.2.18**, Psycopg **3.3.6**, libpq **18.6** (integer `180006`),
  PostgreSQL **16.15**. Both app processes use Django database sessions and the
  same private signing secret. Source and base-image hashes are in each report.
- The default preview image rebuilt after this stage is
  `sha256:59687a2e7a660b1d21d1179b0a66101689938d07e2638dae98c4f62a26c21693`.
  Only the app processes were rolled; existing databases and catalogs remain.

GitHub Actions now runs this fixture alongside frontend and isolated backend
checks. Hosted execution is reported separately. The fixture uses a small
gateway API to prove persistence coordination, rather than gateway runtime
policy. Its root app containers and database-owner role enable failure injection;
they are not production permissions evidence.

## Retained failures and corrections

[Initial run](2026-10-12-postgres-api.json): migration checks imported the URL
configuration, which bootstrapped accounts before their tables existed. Store
resolution is now lazy; migrations and configuration checks work on a clean
database without application-table queries during URL loading.

[Second run](2026-10-12-postgres-api-repeat.json): the 21-case account suite exited
successfully, but the fixture tried to parse its human stdout as JSON. It now
reads that suite's saved JSON report.

[Third run](2026-10-12-postgres-api-third.json): the first 12 groups passed; the
rotation assertion accidentally reread the updated password file as its old
password. The fixture now preserves the original credential separately for that
check. Both complete repeats pass all 13 groups. All failed fixtures were also
removed; their reports remain versioned.

## Remaining release work

The [user guide](../../../docs/guide/postgres-accounts.md) describes configuration,
explicit migration, session behavior, rotation and restore. Production chart and
Compose cutover, real-gateway integration in this storage mode, database TLS,
restricted application/migration roles, durable storage and backup operations
remain open.

The optional pure-Python Psycopg requirement has its original license, exact
wheel/source references and advisory snapshot under
`components/control-plane/licenses/`. PyPI reports no advisories for 3.3.6 in
that snapshot. The default preview image does not install the optional driver.
The final native `libpq` distribution and its transitive source/notices still
need packaging work; disposable binary-wheel testing does not select or clear
that release artifact. Community and Enterprise application licenses are unchanged.
