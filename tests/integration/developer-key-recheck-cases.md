# Check a saved provider key

Run `python -m pytest tests/integration/test_developer_key_recheck.py tests/integration/test_runtime_key_recheck.py tests/unit/test_cli_provider_keys.py tests/unit/test_cli_key_list.py`.

| Case | Expected result |
| --- | --- |
| Saved key receives 401/403 from its approved provider | Record `refused`; status and project key list show it. Dispatch cannot resolve that key. |
| Provider accepts a later check or a validated replacement | Restore `added`; keep the saved key unchanged during a check. |
| Timeout, unavailable provider or unverifiable response | Return an error and preserve the previous verdict and file. |
| Model definition changes before contact or before recording a refusal | No new verdict; before-contact changes send no key. |
| Replacement is refused | Preserve the old key and its previous verdict. |
| Missing key or another owner | Report only this owner's missing registration; no provider call. |
| Cookie-only, invalid or withdrawn account | Reject before provider contact; the current owner lock serializes checks with key mutations. |
| Client supplies a key, owner, filename, fingerprint, duplicate fields or oversized body | Reject; the server chooses its own saved key and exact definition. |
| Commit or private-file failure | Preserve the old verdict; no secret is returned. |
| CLI check/list/status | No key prompt or local key copy; check sends only the model ID, once. Listing makes no provider call. |

This adds an explicit check, not automatic observation of every native provider
response. Unverified gateway errors never become trusted key-refusal verdicts.
