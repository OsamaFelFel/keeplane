# Spec 003 account and edition cases

**Edition:** Open Source. Run against the protected Docker preview at `http://127.0.0.1:3000` with [`test_accounts.py`](test_accounts.py). The test uses temporary users, reports only status and identifiers, and removes its users after the run.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| ACCT-01 | Open the UI and Users API without signing in. | The browser sees sign-in; the API returns 401. |
| ACCT-02 | Sign in with the first admin. | Users and the model API open. |
| ACCT-03 | Sign out, then call the Users API with that browser. | The session no longer works. |
| ACCT-04 | Create a developer and an admin. | Both appear with the chosen roles. |
| ACCT-05 | Try to use the admin UI with a developer account. | The current account trial refuses admin access. The designed developer page belongs to the next account stage. |
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

The HTTP suite does not prove visual layout. Compare Users and Editions in a browser with the supplied canvas. Team behavior is absent from Open Source.
