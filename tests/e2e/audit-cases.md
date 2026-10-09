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
| AUD-09 | Sign in as a temporary developer and try Audit. | The proxy denies the sign-in for the admin-only preview; an unauthenticated Audit request is refused. |

The held-back-request and model-answer switches can be set independently. Their
event producers await the detection and developer-task flows. This run does not
claim those record scenarios are complete.
