# Sign in through your browser

This experimental command needs macOS or Linux, Python 3.9+, a browser and a
trial Keeplane server with browser authorization, token exchange and the current
account route. The issuer is not included in the packaged preview yet. Current
client tests use a controlled HTTP issuer; they do not prove Django consent or
the complete deployed sign-in flow.

Choose a private profile outside Git. Its parent directory must already exist.

```sh
python3 components/cli/browser_login.py \
  --server https://keeplane.example \
  --profile /absolute/private/keeplane-account
python3 components/cli/account_session.py whoami \
  --profile /absolute/private/keeplane-account
```

Sign in and approve the request in your normal browser. Keeplane checks the
returned credential against the current account before saving it. An existing
signed-in profile is refused; explicitly log out or forget it before switching.
The [profile guide](cli-account-profile.md) covers storage and logout recovery.

Each attempt uses fresh state and an S256 PKCE verifier. The temporary listener
accepts only `http://127.0.0.1:{ephemeral-port}/callback`, with its exact Host,
state and optional issuer. Foreign, duplicate or malformed callbacks cannot
complete the flow. The authorization code is exchanged only with the configured
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
The external browser process is not owned, sandboxed or closed by this command.
If account verification or saving fails after issuance, the client attempts to
revoke the new pair. An unconfirmed-revocation error needs server-side session
withdrawal by the installation operator. A failed durable save may leave a
revoked local credential; use logout to remove it after confirmed withdrawal.

Device fallback, automatic refresh and account-bound coding/resume integration
remain separate steps. This trial does not select the release CLI runtime.

The flow follows [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252) and
[S256 PKCE](https://www.rfc-editor.org/rfc/rfc7636).
