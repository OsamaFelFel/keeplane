# Spec 003 account and edition cases

**Edition:** Open Source. Run against the protected Docker preview at `http://127.0.0.1:3000` with [`test_accounts.py`](test_accounts.py). The test uses temporary users, reports only status and identifiers, and removes its users after the run.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| ACCT-01 | Open the UI and Users API without signing in. | The browser sees sign-in; the API returns 401. |
| ACCT-02 | Sign in with the first admin. | Users and the model API open. |
| ACCT-03 | Sign out, then call the Users API with that browser. | The session no longer works. |
| ACCT-04 | Create a developer and an admin. | Both appear with the chosen roles. |
| ACCT-05 | Sign in as a developer, then request admin APIs. | The developer page opens; account and model APIs refuse admin access. |
| ACCT-06 | Sign in with the new admin. | The admin UI opens. |
| ACCT-07 | Create enough users for two pages, then search. | Pages do not repeat users, and search narrows the list. |
| ACCT-08 | Try every former Team route and mutation as an admin. | The API and web paths return 404. |
| ACCT-09 | Open each live admin screen and Editions. | No navigation points to Teams; Editions lists the two editions and the note switch. |
| ACCT-10 | Change an account without Keeplane's action header. | The change is refused. |
| ACCT-11 | Open sign-in. | There is no self-registration control. |
| ACCT-12 | Call the model API with and without an admin session. | Admin succeeds; anonymous caller gets 401. |
| ACCT-13 | Turn the one-time note off, then on; visit twice. | Off shows nothing; on shows the line once for that admin. |
| ACCT-14 | Forge a forwarded-user header without a session. | Keeplane refuses the request. |
| ACCT-15 | Use a wrong first-admin password. | Sign-in and account API refuse access. |
| ACCT-23 | Send sign-in from Keeplane's own browser origin, then from an unrelated origin. | Own origin succeeds; unrelated origin is refused before a session is issued. |
| ACCT-16 | Search for the first admin in Users. | Its account appears as an infrastructure-managed break-glass admin. |
| ACCT-17 | Try to change the first admin's role. | Keeplane refuses the change. |
| ACCT-18 | Repeat a create-user request with the same operation ID, then check its result. | One user is created and both requests return that user. |
| ACCT-19 | Reuse an operation ID with different account details. | Keeplane rejects the conflicting request. |
| ACCT-20 | Promote a developer with an active session, then demote them. | Admin access begins after promotion and the old session is invalid after demotion. |
| ACCT-21 | Install an isolated local account store with an infrastructure password. | The first admin can sign in and is listed as managed break-glass. |
| ACCT-22 | Change the mounted break-glass password and restart the isolated account store. | The old password and session stop working; the new password works. |
| ACCT-24 | Use five wrong passwords for a disposable account, then its correct password with different username casing. | The next attempt returns 429 and Retry-After, with no session cookie. |
| ACCT-25 | Repeat the same attempts for a nonexistent account. | The limit and error match an existing account; no session is issued. |
| ACCT-26 | Submit an array instead of sign-in details. | The API returns 400, and the caller stays anonymous. |
| ACCT-27 | Submit arrays to Create user, Change role and Editions preferences. | Each API returns 400 without changing account state. |

`test_local_identity.py` runs ACCT-17, ACCT-21 and ACCT-22 without a Docker stack. The HTTP suite does not prove visual layout. Compare Users and Editions in a browser with the supplied canvas. Team behavior is absent from Open Source.

`test_account_security.py` runs ACCT-24–ACCT-27 against either preview, using
disposable accounts. The [isolated limit cases](../integration/login-limits-cases.md)
also cover concurrency, restart, expiry, credential rotation and storage failure.

## Spec 003 scenarios (ST6–ST8, ST28)

Each scenario in Spec 003 and the cases that prove it. LA cases are the
[account API cases](../integration/local-accounts-cases.md), UI cases the
[React unit cases](../unit/ui/cases.md) and BR/BSEC cases the
[browser cases](../browser/users-cases.md). ACCT cases are the live cases above.

| Story | Scenario | Checked by |
| --- | --- | --- |
| ST6 | An admin signs in | LA-01, ACCT-02, BSEC-01, BR-02 |
| ST6 | A developer opens the web UI | LA-02, ACCT-05, BR-11 (layout), BR-12 (live) |
| ST6 | Sign out | LA-01, ACCT-03, BSEC-01, BR-12 |
| ST6 | No single sign-on yet | LA-03, UI-SIGN-01, BR-01 |
| ST6 | Single sign-on connected | UI-SIGN-02 shows the option when the server reports a provider. No provider can be connected yet; the end-to-end case waits for task 003-04. |
| ST7 | First sign-in after install | ACCT-21, ACCT-02, BR-02; rotation keeps the same account: ACCT-22, LA-05 |
| ST7 | The break-glass admin in Users | LA-04, ACCT-16, ACCT-17, UI-USERS-01, BR-02 |
| ST8 | Create a user with a role | LA-06, UI-02, ACCT-04, BR-12 |
| ST8 | Developer by default | UI-01, BR-02; the API needs an explicit role: LA-07 |
| ST8 | No answer | UI-03 (10 seconds, Check and Cancel), UI-05 (server errors), UI-06, BR-04 |
| ST8 | Check finds the user | UI-03, LA-09, ACCT-18 |
| ST8 | Check doesn't find the user | UI-04, LA-09, LA-10, BR-04 |
| ST8 | Sent twice | LA-08, UI-04, ACCT-18, ACCT-19, BR-04 |
| ST8 | Find a user | LA-11, UI-USERS-02, ACCT-07, BR-07 |
| ST8 | No self sign-up | LA-03, UI-SIGN-01, ACCT-11, BR-01 |
| ST28 | Change a role | LA-12, BR-05, BR-12, ACCT-20 |
| ST28 | The break-glass admin | UI-USERS-01, BR-02, LA-04, ACCT-17 |
