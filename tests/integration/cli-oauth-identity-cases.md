# CLI OAuth account cases

Run `test_cli_oauth_identity.py` with the separate trial dependencies and
`-m optional`. Each case uses a disposable database and synthetic credentials.

- A bound, unexpired runtime credential resolves the current Keeplane account;
  access and refresh token columns contain no reusable token.
- Account role, activity, password, expiry and current account binding are checked
  again. Unbound tokens, unknown clients, incorrect grants/scopes and plaintext
  token records are refused. Turning acceptance off refuses the next request.
- OAuth credentials cannot serve as browser session cookies. Protected model
  listing and the private gateway callback still check the current project class
  and complete model definition. Project registration derives the current account.
- Explicit CLI logout revokes its own access/refresh pair while preserving another
  CLI credential and browser session. A cookie alone cannot revoke either.
- Global revocation removes account bindings, grants, approved device grants and
  native sessions atomically. Rollback preserves access. Account deletion still
  cascades with acceptance off and preserves another account's credential.
- Issuance refuses an account whose password changed after authorization. A
  database outage returns an unavailable response without exposing credentials.

`test_cli_oauth_browser.py` adds the actual Toolkit HTTP issuer:

- Native browser sign-in, current-account consent and Cancel preserve the state
  parameter; only approval creates a bound code. First-admin sign-in keeps Audit.
- S256 and the exact loopback redirect are required. Wrong verifiers/redirects,
  code replay, edited clients, duplicate fields and unsupported scope are refused.
- Consent and existing browser writes retain CSRF. The dedicated form token
  endpoint accepts only explicit code/refresh grants; cookies provide no authority.
- Refresh rotation, old-token family replay protection, password/global/session
  withdrawal, disabled accounts and missing bindings are checked through HTTP.
- Withdrawal before the owner lock is observed from the live grant, even when
  the password hash is unchanged. Binding failure rolls issuance back completely.
- Trial-off and insecure public-origin settings refuse issuance. Unknown request
  members cannot choose account, role, scope or resource authority.

`test_cli_oauth_journey.py` runs the reviewed CLI over real WSGI HTTP: browser
sign-in/consent, callback, private profile, current account, first-use registration,
authorized catalog and exact logout. The controlled browser submits real CSRF
forms but does not render the React app. A synthetic gateway supplies metadata
only; no provider request occurs in that case. Token/runtime requests carry no browser cookie.

Its optional native coding case uses the same real browser issuer and private
profile, then actual V2 read/edit tools and resume. A synthetic model fixture
calls the actual Django private authorizer for every model request. Withdrawing
approval after the CLI precheck stops dispatch; logout also rejects a copied old
token. Private history contains no account or gateway credential. This fixture
does not implement or prove the installed native gateway listener.

Device protocol, PostgreSQL concurrent issuance, a real browser and the complete
installed native gateway journey remain separate acceptance checks. Set both
`KEEPLANE_CLI_SOURCE` to the reviewed coding CLI repository snapshot and
`KEEPLANE_OPENCODE_V2_BIN` to the pinned runtime to run the native case.

`test_cli_oauth_rendered_browser.py` replaces the HTTP form driver with Chromium.
It renders the compiled React sign-in page, signs in with a disposable developer,
returns to the real consent page and follows the CLI's loopback callback. The
CLI then reads its account, registers a project, lists models and logs out.
Browser sign-in and consent keep CSRF; runtime/token requests carry no browser
cookie. No provider request or native coding turn runs in this case.

Run it with `-m optional`, the issuer dependencies and reviewed CLI source.
Set `KEEPLANE_BROWSER_NODE` to Node with the locked `tests/browser` Playwright
dependencies and Chromium installed. Set `KEEPLANE_BROWSER_UI` to the admin-ui
directory containing its compiled `dist`. The helper blocks non-loopback URLs
and suppresses browser errors and callback URLs in test output.
