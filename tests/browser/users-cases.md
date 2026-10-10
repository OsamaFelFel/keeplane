# React Users browser cases

Run `npm ci && npx playwright install chromium --only-shell && npm test` from
`tests/browser/` while the local Docker preview is running. Tests live under
the repository's top-level `tests/` tree, as required by ADR 017. The browser
suite uses the real local sign-in for BR-02; the layout and network-failure
cases use fixed API responses so they do not create accounts or depend on the
current database contents.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| BR-01 | Open the React sign-in screen without a connected SSO provider. | Username and password appear; SSO and self-registration do not. |
| BR-02 | Sign in with the infrastructure admin and open Create user. | Users opens, the break-glass row has no Change role, and Developer is preselected. |
| BR-03 | Open Users at 1280px and 320px, then open the narrow menu. | Approved screenshots remain stable; the narrow menu is 288px, the table scrolls within the page, the page itself does not overflow, the search field is at least 44px high, and no browser asset is fetched from another origin. |
| BR-04 | Let Create user wait ten seconds without an answer, choose Check, then retry. | The form reports uncertainty, retains the fields after a definite non-write, and retries with the same operation ID. |
| BR-05 | Change a Developer to Admin from Users against a fixed API response. | The UI calls the role endpoint, reports the new role and updates the row. |
| BR-06 | Open Create user, press Escape, then Enter. | Focus returns to Create user and the keyboard reopens the dialog. |

The real Docker account and Audit suites separately test backend permissions,
database effects and idempotent writes. Browser mocks here isolate UI behavior.
