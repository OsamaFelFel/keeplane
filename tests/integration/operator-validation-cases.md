# Preserve private operator model validation

Run `python -m pytest tests/integration/test_operator_validation.py`.
These HTTP checks cover a private callback, not an installed listener.

| Case | Expected result |
| --- | --- |
| Both current private credentials, exact operator marker and constant model metadata | Return only `allowed: true`, without consulting developer policy or enrollment. |
| Developer Bearer, either missing/wrong/non-ASCII credential, or protected/forged marker | Deny without gateway, provider or identity-service contact. |
| Either private secret is atomically replaced | Reject its old value immediately. |
| Current runtime secret is unavailable or malformed | Fail closed with a generic response. |
| Body contains project/actor/prompt fields, duplicate JSON, invalid fingerprint or excessive bytes | Refuse the request. |
| Existing gateway mode, wrong method or content type | Refuse the request. |
| Personal model | Deny before resolving a developer key; keyless/shared and preapproval validation remain available. |

The pinned gateway source at revision
`ea5608642b9d5c94c5baf5fd9f2f9849b808e963` supports CEL-computed HTTP
authorization paths and bodies in `http/ext_authz.rs` (`Protocol::Http` and
`check_http`). Its `types/local.rs` rejects conditional `extAuthz` on backend
targets. The installation therefore needs an unconditional selected-model check
whose path and body depend on a listener-overwritten marker. This file records
that source boundary; it is not evidence that a native policy has compiled or
that a serving gateway strips headers correctly. Those controls remain required
before enabling the installation.
