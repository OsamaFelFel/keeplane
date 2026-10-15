# React Users and account API — 10 October 2026

**Edition:** Open Source. **Code:** `fd25ae4` on `feat/react-users-stack`.
The Docker preview serves the React Users screen from `/users` (redirecting to
`/app/`). The Python account API and agentgateway remain in service. The UI is
built from `components/admin-ui/web/package-lock.json` during local startup.

## Checks and evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Account API and Docker journey | 20/20 passed: Developer sign-in and admin denial, break-glass row and role guard, role changes, paging, idempotent Create user and operation lookup | [Account run](2026-10-10-users-react.json), [cases](../accounts-cases.md) |
| Isolated first-admin lifecycle | 2/2 passed: initial sign-in, password rotation on restart, old session revoked | `python3 tests/e2e/test_local_identity.py`, [cases](../accounts-cases.md) |
| Audit access after Developer sign-in | 9/9 passed, including Developer 403 and anonymous 401 for the Audit API | [Audit run](2026-10-10-audit-developer.json), [cases](../audit-cases.md) |
| Complete current-feature regression | 30/30 suites and 157/157 case records passed on a clean feature branch; Docker and kind, real local Qwen, gateway failure, accounts, models and audit all ran | [Full run](2026-10-10-react-full.json), [catalog](../regression-cases.md) |
| React build and dependencies | TypeScript and Vite build passed; npm audit reported zero advisories. The CLI-only scaffolder was removed after it introduced seven high advisories. Radix Icons replaced the ISC-licensed icon package. | [npm audit result](2026-10-10-react-npm-audit.json), `npm run build` in `components/admin-ui/web` |
| Browser inspection | Sign-in, Users, Create user dialog and narrow menu rendered in the local browser. The first admin had no Change role action; Developer was the selected create default; the mark loaded. The mobile menu measured 288 CSS px, matching the supplied narrow canvas. | Manual browser observation at a 728 CSS px viewport; no stored screenshot baseline yet. |
| Running preview after regression | Docker `/app/` and `/health/app` returned 200; kind `/health` returned 200. | Local health requests after the full run. |

The first full run at `5ee6f58` passed 29/30 suites. Its only failure was AUD-09,
which still expected Developer sign-in to be denied. The product account rule
now permits that sign-in and denies admin APIs. The [initial run](2026-10-10-react-full-initial.json)
records the failure; the corrected Audit case and final full run passed.

## Remaining release work

The current account store and HTTP server remain a SQLite/Python trial. The
approved Django and PostgreSQL control plane is not running. Break-glass sign-in
still needs an audit event committed with its session. The Developer screen is
simpler than its canvas, and OpenID Connect is not connected. Automated
Playwright checks at 1280px and 320px, including the 10-second no-answer flow,
remain to be added. The running agentgateway is an integration trial, not the
selected release gateway or proof of the project-bound runtime policy.
