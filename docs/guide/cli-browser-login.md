# Sign in through your browser

Install the [Keeplane CLI wheel](cli-install.md), then sign in to your
installation. You need macOS or Linux, Python 3.9+, a browser and the server URL
from your operator. The server must use an operator-prepared trial image with
browser authorization enabled and the fixed Keeplane CLI client registered;
the ordinary preview image does not include it.

Sign-in uses your existing Keeplane account. Before saving credentials, the CLI
checks that account with the configured server. Browser UI acceptance and the
[installed CLI journey](../../tests/e2e/installed-cli-cases.md) cover sign-in,
consent and logout with synthetic accounts. This is still an integration trial,
not release distribution approval.

Choose a private profile outside Git. Its parent directory must already exist.

```sh
keeplane login --server https://keeplane.example \
  --profile /absolute/private/keeplane-account
keeplane whoami --profile /absolute/private/keeplane-account
```

Sign in and approve the request in your normal browser. Keeplane checks the
returned credential against the current account before saving it. An existing
signed-in profile is refused; explicitly log out or forget it before switching.
The [profile guide](cli-account-profile.md) covers storage and logout recovery.

Each attempt uses fresh state and an S256 PKCE verifier. The temporary listener
accepts only `http://127.0.0.1:{ephemeral-port}/callback`, with its exact Host,
state and optional issuer. Foreign, duplicate or malformed callbacks cannot
complete the flow. Unknown response fields are ignored; success and refusal
cannot be combined. The authorization code is exchanged only with the configured
issuer; redirects, ambient proxies and cookies are excluded. Unknown token
response fields are ignored and never saved or printed; duplicate keys fail.

```mermaid
sequenceDiagram
  CLI->>Browser: Open Keeplane authorization (S256)
  Browser->>Keeplane: Sign in and approve
  Browser->>CLI: Loopback code + state
  CLI->>Keeplane: Exchange code + verifier; check current account
  CLI->>Profile: Save private issuer/account credentials
```

`--timeout 120` sets the browser callback wait; one to 300 seconds is supported.
The listener also closes stalled HTTP connections. Token/account requests retain
a ten-second socket timeout, not a total deadline. Ctrl+C cancels the attempt.
A failed exchange may have completed on the server; this client cannot revoke
credentials it never received.
The external browser process is not owned, sandboxed or closed by this command.
If account verification or saving fails after issuance, the client attempts to
revoke the new pair. An unconfirmed-revocation error needs server-side session
withdrawal by the installation operator. A failed durable save may leave a
revoked local credential; use logout to remove it after confirmed withdrawal.

Use [device sign-in](cli-device-login.md) when this computer cannot open your
browser, or the [coding command](cli-coding.md) for account-bound turns and resume.
Use explicit [refresh](cli-account-profile.md) when needed; refresh is not
automatic and does not happen during a coding turn. This trial does not select
the release CLI runtime.

The flow follows [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252) and
[S256 PKCE](https://www.rfc-editor.org/rfc/rfc7636).
