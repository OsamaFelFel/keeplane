# Audit local preview cases

Run `python3 tests/e2e/test_audit.py` with the protected Docker preview up. The
script writes a dated JSON result in `tests/e2e/runs/`. The authenticated cases
use a temporary data class and clean it up; the test turns recording off again.

| Case | Plain-English action | Expected observation |
| --- | --- | --- |
| AUD-01 | Open Audit and inspect its controls and signed-in identity. | All three independent switches and the search table are present; the actor has a username. A fresh store starts with all switches off and no records, as the store test checks. |
| AUD-02 | Turn on settings changes only, then add a data class. | One settings record names the signed-in admin, the class and the time. Other record kinds remain off. |
| AUD-03 | Edit and remove the class. | Separate records describe the edit and removal in newest-first order. |
| AUD-04 | Search for the temporary class and filter to settings changes. | Matching records appear; a nonmatching search and other kinds show none. |
| AUD-05 | Make an invalid change and save an unchanged class. | Neither action creates a settings record. |
| AUD-06 | Turn settings recording off, then change a class. | The change succeeds and no new settings record is stored. |
| AUD-07 | Reload Audit after the control plane restarts. | Options and prior records persist; paging still returns at most 25 per page. |
| AUD-08 | Attempt to change a switch without the admin action header. | The request is refused and the switch is unchanged. |
| AUD-09 | Sign in as a temporary developer and request Audit records. | The developer page opens, the protected Audit API returns 403, and an anonymous request returns 401. |

## Always-on break-glass sign-ins

Run `python3 tests/e2e/test_break_glass_audit_store.py` for the isolated
transaction and storage-failure cases, and
`python3 tests/e2e/test_break_glass_audit.py` against the protected Docker
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
| BG-09 | Inspect Audit and try to turn off break-glass recording through its API. | The screen shows a checked disabled control and a Show filter; the API rejects the off request. |

The held-back-request and model-answer switches can be set independently. Their
event producers await the detection and developer-task flows. This run does not
claim those record scenarios are complete.
