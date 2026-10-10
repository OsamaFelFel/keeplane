# Audit React browser cases

These cases use a real Chromium browser and the locally built React UI. Audit API replies are controlled so the screen can be tested without changing the owner's records. Run `cd tests/browser && npm test -- audit.spec.ts` for Docker, then `KEEPLANE_BASE_URL=http://127.0.0.1:13000 npm test -- audit.spec.ts` for kind while both previews are up.

| ID | Plain-English case | Expected result |
| --- | --- | --- |
| AU-UI-01 | Open Audit after sign-in with optional recording off. | The three optional switches are off. Break-glass sign-ins are checked, disabled, and available in Show. |
| AU-UI-02 | Turn on settings recording, then reload. | The request includes the admin action header, the selected switch remains on, and other switches do not change. |
| AU-UI-03 | Search records, filter to break-glass sign-ins, page through records, then narrow the window to 320px. | The table follows the API results; only its own frame scrolls horizontally, fields stay at least 44px tall, and desktop/narrow screenshots remain stable. |
| AU-UI-04 | Make an optional switch write fail, then make a filtered records read fail. | The switch returns to its confirmed value, an error appears, and the table does not present old rows as filtered results. |
| AU-UI-05 | As soon as Audit records appear, click Next and wait for the initial search timer to settle. | Page 2 remains selected; the timer cannot return the table to page 1. |

The live API, persistence, access, and sign-in storage cases are in [Audit cases](../e2e/audit-cases.md).
