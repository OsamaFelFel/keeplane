# Authorize a developer-owned provider key

The internal service joins current account, project and model authorization
to the private key resolver. These checks use real Django records and files,
with synthetic gateway definitions and provider-key validation for setup.
They make no provider calls and do not enable an inference endpoint.

| Case | Expected result |
| --- | --- |
| Two developers use the same model | Each gets only their own stored key; a missing key is refused. |
| Replace, then remove a key | The next decision uses the replacement, then refuses the removed key. |
| Sign out, disable the account, withdraw project access or change its class | No private key is read. |
| Withdraw access after the first policy check | The check under the owner lock refuses the key read. |
| The selected definition changes | The captured fingerprint and stored validation must match the current approved definition. |
| A key read fails | The error reveals neither the key nor its file path. |
| Print or JSON-encode the result | Its display hides the key and JSON encoding is refused. |

Run `python -m pytest tests/integration/test_personal_dispatch.py`.
