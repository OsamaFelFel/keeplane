# CLI account profile cases

| Case | Expected result |
| --- | --- |
| Private owned profile; atomic replace | Exact issuer/account/token round trip; files 0600, directory 0700; repr/str redacted. |
| Concurrent use | Stable file lock refuses the second caller. |
| Symlink, hardlink, FIFO, foreign file/owner or unsafe modes | Refused without reading/exporting secrets or paths. |
| Oversized/malformed state; failed replacement | Generic failure; prior credential preserved; temporary write removed when possible. |
| Current-account request | Explicit bearer only; exact schema and saved account ID checked; current role returned; secrets redacted. |
| Logout 204 or 401 | Local credential removed after server success or confirmed withdrawal. |
| Logout outage/redirect | Credential retained; no success claim or redirect follow. |
| Explicit local forget | Local credential removed without any server request or server-revocation claim. |

These tests use a controlled localhost HTTP server, not the actual OAuth issuer.
