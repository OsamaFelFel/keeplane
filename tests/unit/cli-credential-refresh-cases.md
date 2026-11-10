# Explicit refresh cases

| Case | Expected result |
| --- | --- |
| Browser/device v2 or browser v1 profile | One fixed-client exchange, same current actor, rotated pair saved as v2 (v3 with the server's gateway address; see [saved gateway cases](cli-saved-gateway-cases.md)). |
| Unknown/missing client, v1 extra metadata or duplicate JSON | Refuse before any request. |
| Refused (400) | Retain local state; no retry; the CLI says the sign-in has expired and to run `keeplane login` (the whoami line). |
| Outage: no answer or a 5xx (task 009-15) | Retain local state; no retry; the CLI says Keeplane isn't available, the sign-in is kept, and to run `keeplane refresh` again in a few minutes. A later refresh rotates the pair. |
| Other unexpected answer | Retain local state; warn rotation may already have occurred; no retry. |
| Changed actor, unavailable account, unchanged pair, save failure or cancellation after issuance | Revoke the new pair; preserve old local state when replacement has not happened. |
| Failure syncing the directory after replacement | Revoke the new pair; local state can contain that revoked pair. |
| Cleanup 401 versus outage | Already withdrawn is confirmed; unavailable cleanup reported honestly. |
| Transport/output | No cookies, ambient proxies, raw token output or unknown-response persistence. |

The real Django journey also checks device rotation and browser v1 upgrade,
old-access rejection, refresh replay refusal and logout of the new pair. No
automatic refresh, retry, mid-turn refresh or concurrent PostgreSQL claim.
