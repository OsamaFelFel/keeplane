# Keeplane's key-only check on a customer-run gateway

Spec 005 ST18 and Spec 002 ST5. With `GATEWAY_MODE=existing`, Keeplane's own
model setup request reaches each model through `gateway.url` with the
gateway's runtime key and no developer session. The gateway's backend check
sends that unmarked request to `POST /internal/runtime/authorize/runtime-key`,
on the same host as the final check, as the
[gateway guide](../../docs/guide/gateway-configuration.md#keep-keeplanes-own-model-check-working)
describes.

Run `python -m pytest tests/integration/test_runtime_key_check.py`. RKC-06
needs the CLI sign-in packages; CI's CLI sign-in job runs it with
`-m "optional and live"`. The check through a real gateway is XCM-01 and
XCM-08 in the [class mode cases](existing-gateway-class-mode-cases.md).

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| RKC-01 | Send `Bearer <runtime key>` and the gateway credential, with an empty, JSON or text body. | `{"allowed": true}`, not cached, with no key or file name in the answer. No developer policy, Audit record or gateway call. |
| RKC-02 | Send no Bearer, an empty one, a wrong key, a Basic value, non-ASCII, too long, too short, or the key with its case changed or a character added. | 403 "Only Keeplane's runtime key is accepted", without echoing the value. |
| RKC-03 | Send the runtime key with no, a wrong or a non-ASCII gateway credential, or the two keys swapped. | 403. |
| RKC-04 | Send a current developer session as the Bearer. | 403. |
| RKC-05 | Send a signed-in developer's or admin's browser cookie, or the runtime key as a cookie, with no Bearer; then an admin session as the Bearer. | 403 from the key check, not a CSRF failure: a cookie never counts. |
| RKC-06 | Send a current CLI sign-in token as the Bearer. | 403. |
| RKC-07 | Send the right keys with the mode `managed`, unset, `Existing` or anything else, then again with the runtime key file gone. | 403 "Managed gateways use the installed runtime checks" each time; the keys aren't read. |
| RKC-08 | Replace the runtime key or the gateway credential file. | The old value is refused at once; the new one is admitted. |
| RKC-09 | Remove, unset, make relative, corrupt or oversize the runtime key file, or remove the gateway credential file; then use GET, PUT or DELETE. | 503 "Gateway authorization is unavailable" with no file name; other methods 405 with the keys, 403 without. |

IDR-04 in the [identity replica cases](identity-replicas-cases.md) lists the
route as bearer-only: the browser's CSRF check does not apply, and a signed-in
browser's request without a token still opens nothing.
