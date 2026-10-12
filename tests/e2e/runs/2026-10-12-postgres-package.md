# PostgreSQL deployment and driver package — 12 October 2026

**Edition:** Open Source; Enterprise extends the same identity/storage contract.

The chart now has an explicit shared PostgreSQL mode, separate migration
credentials, verified database TLS and configurable app copies. The native
image target builds the unmodified Psycopg 3.3.6 C extension from verified source,
dynamically links libpq 18.6-r0, retains original notices and both corresponding
source archives, and excludes compiler tools from the runtime.

## Validation

- [Final native-package API run](2026-10-12-postgres-package-api-verified.json):
  15/15 groups, including 21 existing account cases and eight CSRF cases,
  concurrency, shared budgets, Audit rollback, expiry, app/database restart,
  fresh-database restore, rotation and class/project invariants. Database loss
  now gives readiness 503 and liveness 200; readiness recovers to 200.
- [Full default-preview regression](2026-10-12-postgres-package-full-regression.json):
  56/56 suites and 338/338 cases, including the six new chart contract cases.
  Data-class mode is restored. Both existing review previews remain available.
- [Final real-gateway deployment](2026-10-12-postgres-deployment-release-package.json):
  7/7 cases cover HTTPS sign-in, verified database TLS and refusal of wrong
  hostname/CA/plaintext, three restricted-role DDL/role refusals, two app copies,
  managed and separately consumed gateway calls, PVC restart and fresh-database
  restore. Both app installations retain the same session, Audit and approvals.
  The fixture removes its namespace and port-forwards.
- [Image/source inventory](2026-10-12-postgres-driver-package.json): the native
  image is `sha256:3a505c9197fe9ad1e15b5b3b40d43e5c02231f781590d76657864e15248e276a`,
  runs as UID 65532, reports driver implementation `c` and libpq `180006`, and
  contains no `gcc`. Both retained source archives match their recorded hashes;
  the extension's installed original license has SHA-256
  `e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118`.

The rebuilt default preview image is
`sha256:5a4c262c1e0ceda6493a6ffc954fcbfba3992f21a4711060f19da6466e35ded0`.
Only app containers were refreshed; running gateway databases and catalogs were
preserved. No UI assets changed, so the preceding browser-security screenshot
and 24-case browser evidence remains applicable; a new browser run is not
claimed for this package-only slice.

The GitHub PostgreSQL job now builds the native image and runs the API fixture
against it. Hosted results must be checked on the current PR head; the earlier
three-job success on `af75c49` predates this package change.

## Retained failures and corrections

The deployment fixture keeps every earlier result. Its initial database startup
used the wrong service group for the pinned Alpine PostgreSQL image (70, not
999). The repeat exposed a missing `sha256:` gateway key-hash prefix and an app
readiness bug: a clean schema has no settings row until its first change. The
failed Helm wait was stopped after diagnosis and its namespace removed.

The next run reached the freshly installed ingress before its asynchronous
route update. A bounded route wait fixes that race. A later probe needed `/app`
on its Python import path. The following existing-gateway case tried to reuse a
file-owned baseline model without its managed ConfigMap fingerprint. Refusal is
correct. The final fixture registers a database-owned model whose revision can
be verified from both gateway modes. None of these failures is erased.

The earlier [native API package run](2026-10-12-postgres-package-api.json) passes
all 15 groups too; the final repeat uses the corrected clean-schema image.

## Remaining release work

This is integration evidence, not release approval. The single-node kind PVC
trial does not prove production volume semantics or database HA. An operated
database, backup scheduling/retention, recovery objectives, encryption and
credential/certificate operations remain required. Multi-node provider storage
and delivery to a customer-run gateway remain separate contracts. The chart
requires existing database Secrets and storage; it does not silently install a
database operator.

Complete native/base-image source, patch and notice inventory and advisory
review before publishing an immutable release. The retained driver sources do
not clear every component in the Python/Alpine base. Runtime trusted project
binding, class/final-destination enforcement and the release gateway selection
also remain open. The Docker/kind review previews still use their preserved
SQLite stores; this stage does not migrate their trial data.
