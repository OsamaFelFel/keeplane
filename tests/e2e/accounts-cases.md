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
| ACCT-16 | Search for the first admin in Users. | Its account appears as an infrastructure-managed break-glass admin. |
| ACCT-17 | Try to change the first admin's role. | Keeplane refuses the change. |
| ACCT-18 | Repeat a create-user request with the same operation ID, then check its result. | One user is created and both requests return that user. |
| ACCT-19 | Reuse an operation ID with different account details. | Keeplane rejects the conflicting request. |
| ACCT-20 | Promote a developer with an active session, then demote them. | Admin access begins after promotion and the old session is invalid after demotion. |
| ACCT-21 | Install an isolated local account store with an infrastructure password. | The first admin can sign in and is listed as managed break-glass. |
| ACCT-22 | Change the mounted break-glass password and restart the isolated account store. | The old password and session stop working; the new password works. |

`test_local_identity.py` runs ACCT-21 and ACCT-22 without a Docker stack. The HTTP suite does not prove visual layout. Compare Users and Editions in a browser with the supplied canvas. Team behavior is absent from Open Source.
