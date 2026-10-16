# Device login client cases

| Case | Expected result |
| --- | --- |
| Actual HTTP pending, slow down and success | Fixed client/scope, waits 5/5/10/10 seconds, checks account and saves private profile. |
| Output and stored state | Only verification address and short code shown; raw device credential absent from output and profile files. |
| Foreign verification address, malformed codes/interval/expiry, duplicate or oversized JSON | Stop before polling; no profile saved. |
| Unknown response fields | Ignored without printing or saving them. |
| Existing profile | Refuse before requesting another code. |
| Refusal, malformed pending response, timeout or cancellation | Stop without retrying an ambiguous exchange or saving a credential. |
| Account or save failure after issuance | Attempt exact new-pair revocation. |
| HTTP transport | No cookies, ambient proxy or redirect forwarding. |

The integration journey separately joins the actual Django device flow, native
browser account and CSRF forms, current actor, registration, model catalog and
pair logout. Set `KEEPLANE_DEVICE_JOURNEY_REQUIRED=1` in its composed server/client
checkout to fail rather than skip when its required issuer fixture is absent.
