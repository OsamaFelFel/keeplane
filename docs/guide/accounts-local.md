# Try Open Source accounts and Editions locally

**Edition:** Open Source. Start the [protected Docker preview](local-preview.md) with `python3 deploy/local/up.py`, then open [Users](http://127.0.0.1:3000/users). Sign in as `first-admin` using the generated password in `/private/tmp/keeplane-accounts-trial/first-admin-password`. The file stays on your machine and outside Git.

An admin can create username and password accounts with either the **Admin** or **Developer** role, search and page through Users, change roles, and sign out. The first admin appears as an infrastructure-managed break-glass account and cannot be changed in Users. A developer can sign in and sees a simple developer page, but cannot use admin APIs. There is no self-sign-up. The React Create user form uses an operation ID so a repeated request creates the account at most once; after a timeout, **Check** queries that operation.

The break-glass password comes from the mounted file. Changing that file and restarting the app updates the password and invalidates its previous sessions. Keep the file private and out of Git. React's account API now uses Django and DRF inside the app container; the account store remains a SQLite development trial. OpenID Connect sign-in is not yet connected, and Keycloak is not installed by this preview.

After five unsuccessful sign-in attempts for the same username within a minute,
the preview asks you to wait. The API returns 429 with a `Retry-After` delay in
seconds. Changing username casing or restarting the app does not reset the
limit. A successful sign-in clears earlier failures. Infrastructure rotation of
the break-glass password also clears that account's limit. Malformed account
requests return 400 rather than changing an account or issuing a session.

Sign-in and all browser changes now require Django's CSRF token and cookie.
The UI obtains a fresh masked token before each change; successful sign-in
rotates it. Sign out sends a protected POST request. Following a GET link to
`/sign-out` does not end a session. If a token is rejected, reload Keeplane and
try again; the UI does not repeat a write automatically. Cookies are marked
Secure when the configured public origin uses HTTPS.

The [Editions page](http://127.0.0.1:3000/editions) lists the Release 1 Open Source and Enterprise scope. The Enterprise feature note appears once for each admin on Users and links to Editions. An admin can turn that note off or back on from Editions; turning it back on permits one more view. “How to get Enterprise” is plain text until a destination is provided.

Team screens and API routes are absent from Open Source.

The [plain-English API cases](../../tests/e2e/accounts-cases.md) cover accounts, role changes, create retries, route denial and Editions. The [full regression](regression-local.md) includes them. The [browser cases](../../tests/browser/users-cases.md) check the real first-admin sign-in, desktop and 320px layouts, keyboard focus, local assets, role changes and the no-answer flow. Run them from `tests/browser/` with `npm ci`, `npx playwright install chromium --only-shell`, and `npm test`. The [UI unit case](../../tests/unit/ui/cases.md) checks validation without writing an account.

The Docker preview is not a production identity system. Shared PostgreSQL
identity, backup, replica behavior and the complete secure session deployment
still need implementation and verification.

The [live security browser cases](../../tests/browser/security-cases.md) verify
both React and static sign-in/sign-out, and a real Editions change followed by
restoration. The [API security cases](../../tests/e2e/csrf-cases.md) check rejected
requests before any mutation and the HTTPS cookie/origin rules.
