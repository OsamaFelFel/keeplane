# Account sign-in safeguards — 12 October 2026

**Edition:** Open Source. This is a local-preview account stage, not production
identity or the PostgreSQL cutover.

## What changed

The account store reserves a shared username budget before checking a password.
Five failed attempts within one minute return 429 with `Retry-After`; a different
username case or app restart keeps the limit. Known and unknown accounts receive
the same limit. Successful sign-in clears earlier attempts in the session
transaction. Rotating the infrastructure password restores first-admin access
without clearing another account's budget. Failed storage refuses sign-in.

Django rejects a non-object sign-in or account mutation with 400. React keeps
the existing generic invalid-credential message for 401 and displays the actual
cooldown or storage error for other failures. The first browser run found that
the previous UI incorrectly labeled every failure as a wrong password; the
status-aware handling corrected that failure. No dependency versions changed.

## Verification

- The eight isolated limit cases pass, including parallel workers, restart,
  expiry, credential rotation, storage outage and no session/Audit on refusal.
- Docker and kind each pass ACCT-24–ACCT-27 at the public HTTP edge.
- The [initial API regression](2026-10-12-account-security-regression.json)
  passed 51/51 suites and 306 recorded cases. Its UI image preceded the React
  error-message correction.
- The [Docker browser run](../../browser/runs/2026-10-12-account-security-docker.json)
  and [kind browser run](../../browser/runs/2026-10-12-account-security-kind.json)
  each pass 10/10 Users cases, including cooldown, invalid credentials and storage
  failure, as well as the existing desktop and 320px screenshots.
- The final full regression against the rebuilt UI passed **51/51 suites and
  306 cases**, with the prior Data Classes modes restored. It is recorded in
  [the final manifest](2026-10-12-account-security-final-regression.json).
- TypeScript build and the existing UI unit test pass. Lint returns success
  with existing React/TanStack warnings; no new warning was introduced in App.
  Python compilation and `git diff --check` pass. The stack-lock cases verify
  unchanged pinned Python package versions and their existing BSD metadata.

The Docker daemon was initially stopped. Restarting it exposed empty directories
where temporary credential files used to be. The existing isolated Kubernetes
Secrets restored those same credentials; no value was printed or committed.
Both protected previews and the customer-run gateway app were rebuilt, with
existing data retained.

## Limits

The budget applies per username in the shared SQLite trial database. It does
not establish distributed PostgreSQL throttling, network-source limits, CSRF
release acceptance, production identity, OIDC or project policy. Those gates
remain open. The architecture and account guide describe this exact scope.
