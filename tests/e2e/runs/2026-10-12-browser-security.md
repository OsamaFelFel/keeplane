# Browser security verification

**Edition:** Open Source; the same browser contract applies to Enterprise.

All browser mutations now pass Django's CSRF checks, including anonymous sign-in,
Ask and runner discovery. Authentication options provide a masked token and an
HttpOnly Strict cookie with a no-store response. Both browser clients obtain a
fresh token before a change and never automatically repeat a write. Successful
sign-in rotates the token. Sign out requires POST; GET does not revoke a session.
The edge forwards the necessary browser headers and sets the internal scheme
from deployment configuration. HTTPS public origins use Secure cookies.

The obsolete account handlers and their opt-out flag are removed. Protected
installs always start the Django listener. An unconfigured chart packaging
probe can still serve assets and health, while its API fails closed with 503.
The Kubernetes app image is
`sha256:dd662f259165d50bf7133e8db14b9608008d2527fc9d0095bcd17db962d8274d`;
Docker serves the matching backend and built UI from its mounted directories.

## Results

- [Final full regression](2026-10-12-csrf-verified-full-regression.json):
  **55/55 suites, 332/332 case records**. This includes eight CSRF cases on each
  preview and four isolated HTTPS cookie/origin/referer cases.
- [Docker browser run](../../browser/runs/2026-10-12-csrf-verified-docker.json)
  and [kind browser run](../../browser/runs/2026-10-12-csrf-verified-kind.json):
  **24/24 cases each**, no skipped or flaky cases. The live React and static
  sign-in/sign-out journeys pass, including a real Editions write and restore.
  Existing desktop and 320px screenshots pass without changing their baselines.
- [Managed TLS/Calico](2026-10-12-csrf-verified-managed-tls.json):
  **11/11 cases**, including protected model setup, calls, replica loss,
  recovery and removal. The fixture namespace is removed.
- [Customer gateway TLS/Calico](2026-10-12-csrf-verified-existing-tls.json):
  **5/5 cases**, including protected model setup and calls, blocked sibling
  access and the public-route guard. Both fixture namespaces are removed.
- Frontend build, five UI unit tests and lint pass. Existing lint warnings and
  the build's bundle-size/local-font warnings remain; no warning was suppressed.
- [Registry advisory snapshot](2026-10-12-application-advisories.json): npm's
  production audit reports zero advisories, and PyPI reports none for the four
  pinned Python API distributions. This snapshot excludes OS/native gateway
  dependencies and dev-only npm packages; it is not a complete security audit.

Pull requests now run automatic frontend build/unit/lint checks and isolated
backend cases. The two GitHub actions are pinned to immutable official commits,
the repository token is read-only, and checkout does not persist credentials.
Hosted execution is reported separately from these local results.

## Retained failures and corrections

The initial browser run failed four screenshot cases because changing sign-out
from a link to a button removed its underline. The supplied appearance was
restored; subsequent full browser runs pass.

An intermediate full regression passed 53/55 suites. Its gateway-outage probe
returned 500 instead of 503 when no account store was configured, and its HTTPS
test result used a different JSON key from the regression runner. Both were
corrected. The focused outage and HTTPS checks and the final 55-suite regression
pass. Initial and intermediate reports remain beside the final evidence.

Shared PostgreSQL identity/settings/Audit, production session deployment,
gateway policy enforcement and complete production packaging remain release
work. This security stage does not declare the SQLite preview release ready.
