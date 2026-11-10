# Sign out of the CLI

Spec 009 ST29 "Sign out". Run:

```sh
keeplane logout
```

Keeplane revokes this CLI's sign-in and its refresh token at the server, then
removes the tokens, the saved gateway address and the account details from the
profile. It keeps only the server address, which isn't secret, so a plain
`keeplane login` signs you in to the same server again; `--server` overrides it.
From then on the CLI sends nothing with that profile until you sign in again. `code`, `models`, `usage`,
`keys` and `register-project` each say "You're signed out of Keeplane, so nothing
was sent. Run `keeplane login` to sign in." and exit 1; `whoami` and `refresh` say
"You're signed out of Keeplane. Run `keeplane login` to sign in." Running `logout`
again says "You're already signed out of Keeplane." Admins sign out the same way.

If the server can't be reached, `logout` keeps the credential and says so; run it
again when the server is back. `keeplane forget` removes only the local copy and
doesn't revoke anything at the server; it keeps the server address too
([profile storage and recovery](cli-account-profile.md)).

### If the kept server address can't be used

Keeplane never trusts or rewrites a kept server address that is damaged or unsafe:
not valid JSON, an extra field, too big, the wrong permissions, or a link. A plain
`keeplane login` then exits 1 and says "Keeplane can't use the server address it
kept for this profile. Run `keeplane login --server <address>`, or `keeplane
forget` to remove it." Either way out works:

- `keeplane login --server <address>` signs in without reading the file. The
  file stays as it was until your next `logout` replaces it with the server you
  signed in to.
- `keeplane forget`, while you're signed out, removes the file (a link is
  removed, never what it points to) and says "Removed the server address Keeplane
  couldn't use. Run `keeplane login --server <address>` to sign in." With a
  usable address it removes nothing and says "You're already signed out of
  Keeplane."

```mermaid
flowchart LR
  Logout[keeplane logout] --> Revoke[Server revokes the sign-in]
  Revoke --> Removed[Tokens, gateway and account removed; server address kept]
  Removed --> Nothing[Later commands send nothing]
  Nothing --> Login[keeplane login signs in again to the kept server]
```

## Revoke a test CLI session

Use this experimental command with the matching runtime session-revocation
route. It revokes the supplied Keeplane session at the server. Browser/PKCE
sign-in and local credential storage are separate changes.

```sh
python3 components/cli/session_logout.py --server https://keeplane.example
```

Enter the current Keeplane test session at the hidden prompt, or supply it
through the `KEEPLANE_SESSION_CREDENTIAL` secret environment. Never enter a
provider key or a secret command-line argument.

```mermaid
flowchart LR
  CLI[Explicit current session] --> Revoke[Server revokes that session]
  Revoke --> Denied[Next authenticated request is refused]
```

Success prints `Keeplane session revoked.` only after a 204 response. If the
session is already unavailable, the server refuses the request. A connection
failure does not confirm revocation; retry against the same server. Other
sessions and provider keys are untouched. HTTPS, redirect refusal, sanitized
errors and response limits follow the [catalog connection](cli-server-connection.md).
