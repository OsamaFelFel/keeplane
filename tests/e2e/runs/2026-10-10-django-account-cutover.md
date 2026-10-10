# Local Django account API cutover

**Edition:** Open Source. Run on 10 October 2026. React's account requests on
the public Keeplane addresses now pass through Django 5.2.18 and DRF 3.18.3.
The Django listener is bound to loopback inside each app container. The model,
Data Classes and Audit HTTP routes still use the earlier Python server; the
existing local account use cases still own the SQLite trial data. Docker's
existing account files were retained, with a repeatable volume ownership step
for the non-root app image. Kind retained its separate PersistentVolumeClaims.

| Plain-English check | Observed result | Evidence |
| --- | --- | --- |
| Run the account flow against a separate Django-backed container before replacing the live preview. | 21/21 pass on port 13001; trial state was temporary. | [Isolated accounts](2026-10-10-django-isolated-users.json) |
| Sign in, manage users, change roles, use Editions and reject a foreign origin on the live Docker and kind previews. | 21/21 pass on each port. | [Docker accounts](2026-10-10-django-docker-users.json), [kind accounts](2026-10-10-django-kind-users.json) |
| Keep Data Classes and Audit available through Django sign-in and restart the kind app without losing changes. | 11/11 Data Classes and 9/9 Audit cases pass, with cleanup complete. | [kind Data Classes](2026-10-10-django-kind-data-classes.json), [kind Audit](2026-10-10-django-kind-audit.json) |
| Recheck Docker, kind, gateway failover, local Qwen, provider keys and the pinned dependency stack. | 33/33 suites, 174 case records pass. | [Full regression](2026-10-10-django-account-regression.json) |
| Use the real React screens with keyboard and responsive layout checks. | Playwright: 13/13 passed (`npm test` in `tests/browser`). | The named browser cases are in [Users](../../browser/users-cases.md), [Data Classes](../../browser/data-classes-cases.md) and [Audit](../../browser/audit-cases.md). |
| Try the Django port from inside Docker and kind, then from the developer host. | Internal `/api/auth-options` returned HTTP 200 in both app containers; host `127.0.0.1:8765` refused the connection. | Direct port probe on this run. |

The local dependency lock checks exact installed versions in Docker and kind
and checks package metadata for a BSD license. The wheels retain their license
files in the image. This stage does not yet replace the SQLite use cases with
Django ORM, use PostgreSQL for account persistence, or use Django's session and
CSRF machinery. Those remain release backend work under ADR 016. Django's
standard PostgreSQL driver, Psycopg, is LGPL-3.0 and is outside the current
customer-installed component license list; production packaging needs an
approved license decision or a tested compliant driver/backend choice.
