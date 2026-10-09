# Try Open Source accounts and Editions locally

**Edition:** Open Source. Start the [protected Docker preview](local-preview.md) with `python3 deploy/local/up.py`, then open [Users](http://127.0.0.1:3000/users). Sign in as `first-admin` using the generated password in `/private/tmp/keeplane-accounts-trial/first-admin-password`. The file stays on your machine and outside Git.

An admin can create username and password accounts with either the **Admin** or **Developer** role, search and page through Users, and sign out. There is no self-sign-up. This local account store is SQLite and is still a development trial. The developer web page, break-glass credential rotation and OpenID Connect sign-in are later account work; Keycloak is not installed by this preview.

The [Editions page](http://127.0.0.1:3000/editions) lists the Release 1 Open Source and Enterprise scope. The Enterprise feature note appears once for each admin on Users and links to Editions. An admin can turn that note off or back on from Editions; turning it back on permits one more view. “How to get Enterprise” is plain text until a destination is provided.

Team screens and API routes are absent from Open Source.

The [plain-English cases](../../tests/e2e/accounts-cases.md) cover accounts, route denial and Editions. The [full regression](regression-local.md) includes them. Compare the live Users and Editions pages to the product canvas in a browser as well as running HTTP cases.

The Docker preview is not a production identity system. The release identity component, backup, replica behavior and secure session deployment remain to be selected and tested.
