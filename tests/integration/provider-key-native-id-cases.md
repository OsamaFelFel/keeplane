# Provider validation native ID cases

| Case | Expected result |
| --- | --- |
| ID omitted or exact matching string | Existing OpenAI/Anthropic validation request and complete fingerprint retained. |
| Wrong, empty, null, numeric, array or object ID | Refuse before contacting the provider, even with current approval. |
| Matching ID added after approval | Refuse until the complete new definition is approved; no old fingerprint transfer. |
| Other unsupported fields, authentication or provider formats | Existing strict checks still apply. |

These synthetic HTTP cases do not enable personal-key dispatch or attest a
native destination. Protected envelopes remain outside the supported schema.
