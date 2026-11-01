# Accounts and sign-in

Start Keeplane using the [local setup guide](local-preview.md). Open the printed
address and sign in as `first-admin`, using the printed password-file location.
Open **Users** to manage accounts.

## Create an account or change its role

Choose **Create user**, enter a username and password, and choose Admin or
Developer. Developer is selected by default. Search and paging help find an
existing user; **Change role** updates their access.

If Keeplane doesn't answer within ten seconds, the dialog says it isn't clear
whether the user was created because Keeplane didn't answer in time. If Keeplane
answers with a server error, it says Keeplane couldn't confirm the result. Both
offer **Check**. Use it to find whether the account was created before retrying. If
Check finds nothing, the form comes back with what you typed; sending it again
creates at most one account. Only when Keeplane refuses the request, for example
because the name is taken, does the dialog say nothing was saved. There is no
self-sign-up.

Developers see a page explaining that the web application is for admins. They
cannot open admin APIs. Single sign-on is not connected yet.

## The infrastructure admin

The first admin is marked as managed by infrastructure. Users cannot edit,
remove or change its role through the UI. Each successful sign-in is recorded in
Audit; that record cannot be switched off.

Its password comes from the credential file printed at startup. To rotate it,
update that file and restart Keeplane using the same local setup command and
credential directory. Rotation preserves the account and revokes older sessions.
Keep the file private and outside Git.

## Sign-in failures and sign-out

After five unsuccessful attempts for one username within a minute, wait for the
delay shown on screen. Changing username casing or restarting the application
keeps the limit. If storage is unavailable, the UI explains that separately.

Use **Sign out** to end a session. If a browser security token is rejected, reload
Keeplane and try again; the UI does not repeat a write automatically.

The **Editions** page explains feature availability and lets an admin switch the
one-time Enterprise feature note off or on.

## Current installation

All account and session storage uses Django. The single-process local application
uses SQLite through Django ORM. The optional [PostgreSQL backend](postgres-accounts.md)
has integration tests for shared sessions, accounts, settings, Audit and recovery;
production operations and local-preview cutover remain work.

See the [account cases](../../tests/e2e/accounts-cases.md) and
[test guide](regression-local.md) for verification commands.
