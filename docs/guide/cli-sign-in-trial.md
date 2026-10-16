# CLI browser sign-in trial

The CLI opens Keeplane in your browser. Sign in with your existing account, then
choose **Continue** to allow CLI access. **Cancel** returns to the CLI without
granting access. Your project and model permissions still apply to each request.

A password change, disabled account or global sign-out withdraws CLI access.
CLI logout revokes that CLI's access and refresh pair; another CLI session and
your browser session keep working. Refresh rotates the pair; reusing an old
refresh token withdraws its replacement family.

This is an optional integration trial. It is off by default and is not installed
in the packaged preview. Device sign-in, installed distribution checks and the
complete protected coding journey remain separate work.

For an already configured development server, use Python 3.12 in a virtual
environment, install the control-plane requirements, then the pinned trial graph:

```sh
python -m pip install -r components/control-plane/requirements-account-api.txt
python -m pip install --require-hashes --no-deps \
  -r components/control-plane/requirements-cli-auth.txt
python components/control-plane/manage.py migrate --noinput
python components/control-plane/manage.py register_cli_client
```

Keep the existing database, signing secret, first-admin password file and built
UI configuration. Set `KEEPLANE_CLI_OAUTH_ENABLED=1` when starting that server.
`PUBLIC_ORIGIN` must be its actual HTTPS address; HTTP is accepted only for a
configured loopback host. The CLI and browser must use the same origin. Build
the UI with Node 22.12 or later so browser sign-in can return to the consent page.
Changing the public client record causes issuance to refuse the request; the
registration command will not silently repair a changed record.

The dependency lock covers macOS Python 3.12 and Linux musl Python 3.13 wheels.
Source and licence checks must finish before these dependencies are packaged.
Turning acceptance off keeps installed token models registered for account
deletion. Keep the dependency installed after migrating; removing it requires a
planned schema rollback.

The fixed public client is `keeplane-cli`, with scope `runtime`. Browser consent
uses the existing Keeplane session and CSRF checks at `/oauth/authorize/`.
The CLI receives a code only at `http://127.0.0.1:{ephemeral-port}/callback` and
exchanges it with an S256 verifier at `/oauth/token/`. The token endpoint accepts
form grants, never browser cookies as authority. It also accepts refresh grants.
Unknown protocol extensions cannot change account, scope or grant authority.

`GET /api/runtime/session` returns the current account ID, username and role for
an explicit bearer credential. `DELETE` on the same resource signs its pair out.
Owner locking covers fresh browser/code/refresh checks through issuance and
binding; passwords and current account state are checked again. Access and
refresh records contain hashes rather than reusable tokens. Authorization codes
are short-lived Toolkit grant records; protocol debug logging is disabled.

Run the isolated trial checks with the optional graph installed:

```sh
python -m pytest -q -m optional \
  tests/integration/test_cli_oauth_identity.py \
  tests/integration/test_cli_oauth_browser.py \
  tests/integration/test_cli_oauth_journey.py
```

The journey test needs the shared CLI entry point from the CLI client changes.
Set `KEEPLANE_CLI_SOURCE` to that repository's root when testing a separate
checkout. A missing default checkout is an explicit skip; a supplied missing
path is a failure. It uses real HTTP and Toolkit with synthetic accounts and a
controlled browser driver; it does not render React or contact a model provider.
The security cases cover CSRF, code replay, refresh replay, revocation and issuance
rollback. PostgreSQL concurrent issuance and a real browser remain additional
acceptance checks, not claims made by the SQLite fixture.
