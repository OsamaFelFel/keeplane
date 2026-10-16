# Manage a developer's provider keys

These first-party runtime endpoints let Keeplane's CLI inspect, add, replace and
remove the signed-in developer's own model keys. Configure an absolute
`PROVIDER_KEY_DIR` readable and writable by the app account. Use HTTPS; the local
loopback installation may use HTTP.

Every call sends `Authorization: Bearer <runtime credential>`. Authentication is
checked again under the owner's database lock. Cookies and caller-supplied
owner IDs do not authorize these operations.

| Method and path | Input |
| --- | --- |
| `GET /api/runtime/provider-keys?model_id=...` | Exactly one URL-encoded model ID; no body. |
| `PUT /api/runtime/provider-keys` | JSON containing exactly `model_id` and `key`. |
| `DELETE /api/runtime/provider-keys` | JSON containing exactly `model_id`. |

The model ID is 1–256 characters without control characters. JSON must fit in
4 KiB; duplicate or extra fields are refused. A key is 12–512 non-space ASCII
characters. Collect it through a hidden prompt; keep it out of arguments, URLs,
files and logs. The server never returns it.

Successful calls return 200 with only:

```json
{"model_id":"coder","status":"added","cleanup_pending":false}
```

`status` is `added` or `missing`. It describes the owner's stored registration,
including old/unbound records; it does not promise eligibility, a usable key file
or dispatch. GET contacts neither gateway nor provider. DELETE also works when
the model changes or is withdrawn. `cleanup_pending` means old file deletion
needs retry. DELETE also removes the active registration; it is not a cleanup-only command.

PUT checks the current approved `personal` model and its exact raw definition,
tests the key with that provider, then rechecks the definition before saving.
The narrow OpenAI/Anthropic validator requires HTTPS; loopback HTTP is enabled
only by disposable tests. A provider refusal or failure before commit keeps the
previous key. Model edits require a fresh check; old bindings do not transfer to the changed model.

| Status | Meaning |
| --- | --- |
| 400 / 413 / 415 | Invalid fields, provider refusal, too much data or non-JSON input. |
| 401 | Credential is invalid, expired or revoked; account/password changed. |
| 403 | PUT targets a model not currently set up for developer-owned keys. |
| 503 | Current definition, provider check or storage could not be verified. |

Errors contain no submitted key, filename, fingerprint or provider response.
A 503 can happen after a key commit if cleanup/status confirmation fails. Do not
report that nothing was saved or automatically resend the key. GET can confirm
registration presence and pending cleanup, but cannot identify which key value
was committed. PUT with `added` and pending cleanup already committed its new
registration; DELETE with `missing` and pending cleanup withdrew the active one.
A revoke that obtains the owner lock first blocks a stale request before provider
contact. A key check that obtains it first may finish before that revoke.
The runtime callback still denies personal-key dispatch. Native protected
publication, final key injection and release readiness remain separate work.
