# Sign in using a code

Use this explicit fallback when your terminal cannot open a browser. It needs
macOS or Linux, Python 3.9+, and a trial Keeplane server with device authorization
enabled. The operator must register the fixed device client with
`python manage.py register_cli_client --device`. The trial server and CLI are
not yet packaged together.

Choose a private profile outside Git, with an existing parent directory:

```sh
python3 components/cli/keeplane.py login --device \
  --server https://keeplane.example \
  --profile /absolute/private/keeplane-account
```

Open the printed Keeplane address in your browser, enter the short code, sign in
and choose Continue. The terminal waits for approval, checks your current account
and saves the private profile. An existing signed-in profile is refused before
starting another attempt. Then use the usual `whoami`, project, key, coding and
`logout` commands. [Profile storage and recovery](cli-account-profile.md) apply.

The client waits the server's polling interval before every exchange and adds
five seconds when asked to slow down. `--timeout 120` bounds the approval wait;
one to 300 seconds is supported, and server expiry can shorten it. Requests use
bounded responses and socket timeouts; this is not a hard total network deadline.
There is no automatic fallback from a browser exchange or retry after an
ambiguous token exchange.

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
