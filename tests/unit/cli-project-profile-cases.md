# CLI profile and project commands

| Case | Expected result |
| --- | --- |
| One entry point: login | Real controlled-issuer PKCE/profile checks also pass through the shared command. |
| Current account → register → models → logout | Correct ordered HTTP requests; canonical UUID and server name preserved; only saved issuer/current bearer used, no cookies or account claims. |
| Actor changed, 401 or 503 before project command | Both register and models stop after account check; no project request or leaked credential. |
| Server model metadata contains a credential | Access and refresh values are redacted from command output. |

These are synthetic HTTP controls. No inference, initialization or release
issuer acceptance is claimed.
