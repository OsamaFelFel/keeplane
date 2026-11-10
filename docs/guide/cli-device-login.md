# Sign in using a code

`keeplane login` uses this code by itself when it can't open a browser: over SSH,
with no display, when no browser can be found, or when the browser fails to start (see
[browser sign-in](cli-browser-login.md#when-no-browser-can-open)). Use `--device`
to choose it yourself. It needs
macOS or Linux, Python 3.9+, and a Keeplane server with device authorization
enabled. The [local preview](local-preview.md) has it on and registers the fixed
device client; for other servers see
[CLI sign-in on the server](cli-sign-in-server.md). The [CLI wheel](cli-install.md) installs `keeplane`
without the server or native coding runtime.

Choose a private profile outside Git, with an existing parent directory:

```sh
keeplane login --device --server https://keeplane.example \
  --profile /absolute/private/keeplane-account
```

Open the printed Keeplane address in your browser, enter the short code, sign in
and choose Continue. The terminal waits for approval, checks your current account
and saves the private profile. An existing signed-in profile is refused before
starting another attempt, unless the server says its sign-in has expired: then
`login` removes it and signs you in again. Admins approve the code the same way
and then work like developers, with the same project and model limits. Then use the usual `whoami`, project, key, coding and
`logout` commands. [Profile storage and recovery](cli-account-profile.md) apply.

The client waits the server's polling interval before every exchange and adds
five seconds when asked to slow down. `--timeout 120` bounds the approval wait;
one to 300 seconds is supported, and server expiry can shorten it. Requests use
bounded responses and socket timeouts; this is not a hard total network deadline.
Once a browser has opened, the CLI does not switch to a code: a browser sign-in
that times out or is refused stops there. There is no retry after an ambiguous
token exchange.

Ctrl+C stops polling and leaves no signed-in profile. A pending code expires on
the server; cancellation does not remotely revoke it. An exchange may finish on
the server even if its response is lost. After receiving credentials, account or
save failures trigger a best-effort pair revocation, with unconfirmed cleanup
reported explicitly. Use operator withdrawal when that cleanup cannot be confirmed.

Only the short code and exact configured verification address are printed. The
raw device credential remains in memory, is sent only to the configured issuer,
and is never saved. Redirects, ambient proxies and cookies are excluded. Unknown
response fields are ignored; malformed or duplicate fields stop the attempt.

Tests join this command to the actual Django device approval, current account,
project registration, model listing and logout routes using synthetic accounts.
They cover HTTP behavior without rendering the browser UI or contacting a model.
This remains an integration trial, not a release runtime selection.
