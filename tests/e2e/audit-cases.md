# Audit local preview cases

Run `.venv/bin/python -m pytest tests/e2e/test_audit.py -m live` with the protected Docker preview up. The
script writes a dated JSON result in `test-results/`. The authenticated cases
use a temporary data class and clean it up; the test turns recording off again.
[Persistence cases](../integration/audit-persistence-cases.md) check Show,
search and paging across two app processes, a restart and an upgrade.

| Case | Plain-English action | Expected observation |
| --- | --- | --- |
| AUD-01 | Open the React Audit route and inspect its API and signed-in identity. | The page loads with the admin identity and three independently stored optional settings. The browser cases check the visible controls. A fresh store starts with all optional settings off, as the store test checks. |
| AUD-02 | Turn on settings changes only, then add a data class. | One settings record names the signed-in admin, the class and the time. Other record kinds remain off. |
| AUD-03 | Edit and remove the class. | Separate records describe the edit and removal in newest-first order. |
| AUD-04 | Search for the temporary class and filter to settings changes. | Matching records appear; a nonmatching search and other kinds show none. |
| AUD-05 | Make an invalid change and save an unchanged class. | Neither action creates a settings record. |
| AUD-06 | Turn settings recording off, then change a class. | The change succeeds and no new settings record is stored. |
| AUD-07 | Reload Audit after the control plane restarts. | Options and prior records persist; paging still returns at most 25 per page. |
| AUD-08 | Attempt to change a switch without the admin action header. | The request is refused and the switch is unchanged. |
| AUD-09 | Sign in as a temporary developer and request Audit records. | The developer page opens, the protected Audit API returns 403, and an anonymous request returns 401. |

## Always-on break-glass sign-ins

Run `.venv/bin/python -m pytest tests/integration/test_break_glass_audit_store.py` for the isolated
transaction and storage-failure cases, and
`.venv/bin/python -m pytest tests/e2e/test_break_glass_audit.py -m live` against the protected Docker
preview. Neither test saves a password, session token or provider key in its
result.

| Case | Plain-English action | Expected observation |
| --- | --- | --- |
| BG-01 | Sign in with the first admin on a fresh store. | One session and one dated break-glass record are saved; optional record kinds remain off. |
| BG-02 | Try a wrong first-admin password. | Sign-in is refused and no record is added. |
| BG-03 | Sign in again, then search only break-glass records. | A separate second record appears; settings records remain independent. |
| BG-04 | Restart with a rotated infrastructure password and sign in. | Old sessions and password stop working; one new record is saved for the new sign-in. |
| BG-05 | Make the audit store refuse writes, then separately make session storage refuse writes. | Each sign-in returns 503; neither a session nor a record is committed in either failure direction. |
| BG-06 | Repair storage and sign in. | Sign-in works and the records contain no password or session token. |
| BG-07 | Sign in to the running Docker preview and filter Audit to break-glass records. | The latest record names first-admin and describes only the sign-in. |
| BG-08 | Sign in again, then try a wrong password. | The repeat adds one record; the failed attempt adds none. |
| BG-09 | Open Audit and try to turn off break-glass recording through its API. | The React page loads and the API rejects the off request. Browser case AU-UI-01 checks the disabled control and Show filter. |

## Spec 006 scenarios (ST21, ST22)

Each scenario in Spec 006 and the cases that prove it. BGS cases are the
[break-glass sign-in cases](../integration/break-glass-sign-in-cases.md), SC
the [settings-change cases](../integration/settings-change-record-cases.md),
CL-INT the [complexity level cases](../integration/complexity-level-cases.md),
MA the [model answer cases](../integration/model-answer-record-cases.md), HR
the [held-back request cases](../integration/held-request-record-cases.md), AS
the [persistence cases](../integration/audit-persistence-cases.md) and AU-UI
the [browser cases](../browser/audit-cases.md). AUD and BG cases are above.
`tests/unit/test_audit_scenario_map.py` fails if a scenario is missing here or
a case named here has no catalog row or no test.

| Story | Scenario | Checked by |
| --- | --- | --- |
| ST21 | After install | BGS-01, SC-01, MA-01, HR-01, BG-01, AU-UI-01, AUD-01 |
| ST21 | Settings changes | SC-02, SC-07, SC-12, CL-INT-03, AUD-02, AUD-03 |
| ST21 | Held-back requests | HR-02, HR-03, HR-06, HR-08, HR-10, HR-12, HR-13 |
| ST21 | Model answers | MA-02, MA-06, MA-11, MA-14, MA-17 |
| ST21 | Break-glass sign-ins | BGS-01, BGS-02, BGS-03, BGS-04, BGS-05, BGS-06, BG-07, BG-08, BG-09 |
| ST21 | One kind only | SC-03, MA-03, HR-07, AU-UI-02, AUD-02 |
| ST22 | Find records | AS-01, AS-02, AS-03, AS-04, AU-UI-03, AUD-04 |

"Model answers" follows the owner's decision on governance issue #36: a record
is written when Keeplane lets a request through to a model, so "a request that
later fails" keeps the record written when it was sent (MA-17).
