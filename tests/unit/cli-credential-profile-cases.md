# CLI account profile cases

| Case | Expected result |
| --- | --- |
| Private owned profile; atomic replace | Exact issuer/account/token round trip, and gateway address when saved; files 0600, directory 0700; repr/str redacted. |
| Concurrent use | Stable file lock refuses the second caller. |
| Symlink, hardlink, FIFO, foreign file/owner or unsafe modes | Refused without reading/exporting secrets or paths. |
| Oversized/malformed state; failed replacement | Generic failure; prior credential preserved; temporary write removed when possible. |
| Current-account request | Explicit bearer only; exact schema and saved account ID checked; current role returned; secrets redacted. |
| Logout 204 or 401 | Local credential removed after server success or confirmed withdrawal. |
| Logout outage/redirect | Credential retained; no success claim or redirect follow. |
| Explicit local forget | Local credential removed without any server request or server-revocation claim. |
| Sign-out keeps the server | Logout and forget leave only `server.json` (format and server address, 0600, atomic) and the lock; no token, account or gateway. A malformed, oversized, duplicate-key or unsafe `server.json` is refused with one message naming `keeplane login --server <address>` and `keeplane forget`. |
| Unusable `server.json` | An unsafe one (mode, another owner, link, dangling link, hardlink, FIFO, socket) is refused before it is opened, even when its target holds a valid address. It doesn't block opening the profile, so other commands still work; a `server.json` directory still does. `remove_unusable_server` unlinks only a bad entry (never a link's target) and keeps a usable one; sign-out replaces a bad entry with the signed-in server. |

These tests use a controlled localhost HTTP server, not the actual OAuth issuer.
