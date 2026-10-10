# Try Open Source accounts and Editions locally

**Edition:** Open Source. Start the [protected Docker preview](local-preview.md) with `python3 deploy/local/up.py`, then open [Users](http://127.0.0.1:3000/users). Sign in as `first-admin` using the generated password in `/private/tmp/keeplane-accounts-trial/first-admin-password`. The file stays on your machine and outside Git.

An admin can create username and password accounts with either the **Admin** or **Developer** role, search and page through Users, change roles, and sign out. The first admin appears as an infrastructure-managed break-glass account and cannot be changed in Users. A developer can sign in and sees a simple developer page, but cannot use admin APIs. There is no self-sign-up. The React Create user form uses an operation ID so a repeated request creates the account at most once; after a timeout, **Check** queries that operation.

The break-glass password comes from the mounted file. Changing that file and restarting the app updates the password and invalidates its previous sessions. Keep the file private and out of Git. The account store remains a SQLite development trial. OpenID Connect sign-in is not yet connected, and Keycloak is not installed by this preview.

The [Editions page](http://127.0.0.1:3000/editions) lists the Release 1 Open Source and Enterprise scope. The Enterprise feature note appears once for each admin on Users and links to Editions. An admin can turn that note off or back on from Editions; turning it back on permits one more view. “How to get Enterprise” is plain text until a destination is provided.

Team screens and API routes are absent from Open Source.

The [plain-English cases](../../tests/e2e/accounts-cases.md) cover accounts, role changes, create retries, route denial and Editions. The [full regression](regression-local.md) includes them. The React screen follows the supplied theme and Users canvas; compare its narrow and wide layouts in a browser as well as running HTTP cases.

The Docker preview is not a production identity system. The release identity component, backup, replica behavior and secure session deployment remain to be selected and tested.
