# CLI browser sign-in trial

The CLI opens Keeplane in your browser. Sign in with your existing account, then
choose **Continue** to allow CLI access. **Cancel** returns to the CLI without
granting access. Your project and model permissions still apply to each request.

A password change, disabled account or global sign-out withdraws CLI access.
CLI logout revokes that CLI's access and refresh pair; another CLI session and
your browser session keep working. Refresh rotates the pair; reusing an old
refresh token withdraws its replacement family.

This is an optional integration trial. It is off by default and is not installed
in the packaged preview. The server also supports the separate device fallback
described below; its CLI command, installed distribution checks and the complete
protected coding journey remain separate work.

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

For the server's device fallback trial, register its separate public client:

```sh
python components/control-plane/manage.py register_cli_client --device
```

`POST /oauth/device/` accepts a form with `client_id=keeplane-cli-device` and
`scope=runtime`. It returns the standard device/user codes, verification URL,
expiry and polling interval. The person signs in at `/oauth/confirm-device/`,
enters the displayed CLI code, checks the account and chooses Continue or Cancel.
Both browser steps retain CSRF. The current shared CLI login command still uses
the browser callback; a device client joins this server contract separately.

The token endpoint accepts `grant_type=urn:ietf:params:oauth:grant-type:device_code`,
that fixed client ID and the device code. Pending requests return
`authorization_pending`. Early polls return `slow_down` and increase the delay
by five seconds; clients must retain that longer delay. Expiry, cancellation,
changed accounts and withdrawn approval cannot issue tokens. Success consumes
the device approval in the same transaction as access/refresh binding. Refresh
uses the device client ID and retains the existing pair logout/replay behavior.

The trial reuses the existing five-attempt, sixty-second DB budget in separate
hashed buckets: anonymous initiation per direct network peer, code entry per
signed-in account. A limit returns 429 with Retry-After. Forwarded IP headers
cannot reset it; people behind one direct peer share its initiation budget.
The limit is a bounded trial control, not a completed deployment abuse policy.

Stock Toolkit 3.4.1 does not enforce device expiry, consumption, client binding
or pending-poll slowdown at its token view. The Keeplane subclass checks those
lifecycle conditions and delegates protocol/token creation to Toolkit. It locks
the owner before the live device row; an approval that races an unowned pending
lookup defers to a later poll. The actual HTTP tests are in
`tests/integration/test_cli_oauth_device.py`; they remain separate from a real
CLI fallback journey and PostgreSQL concurrency acceptance. No release-component
selection or dependency packaging is implied.
