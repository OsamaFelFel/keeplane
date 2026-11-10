# Browser login client cases

| Case | Expected result |
| --- | --- |
| Actual command through controlled HTTP issuer | Fresh S256/state, exact client/scope/loopback, correct code/verifier/redirect exchange, current account check, private profile, no tokens in output. |
| Unknown token response fields | Ignored; only reviewed credentials retained. |
| Unknown authorization response fields | Ignored without printing or storing; code/error remain mutually exclusive. |
| Wrong callback path/state/issuer/Host or duplicate code | 400 without consuming the pending attempt; later valid response succeeds. |
| Duplicate token JSON keys or invalid required fields | No profile saved; response values never printed. |
| Token exchange refusal or redirect | One exchange only; no forwarding or success claim. |
| Account/storage failure after issuance | Exact issued pair revocation attempted; unconfirmed cleanup reported honestly. |
| Refusal or callback timeout | No token exchange; listener closes, including a partial HTTP request. |
| Browser fails to start | No token exchange; the listener closes and sign-in uses the device code ([no-browser cases](cli-no-browser-cases.md)). |
| Existing signed-in profile | Refused before opening the browser. |

These controls exercise the real client HTTP/listener path with a synthetic
issuer. Actual Django browser identity, CSRF, consent, code replay, revocation
and the device fallback need the server integration checks.
