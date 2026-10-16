# Personal model setup

Admins can register fixed OpenAI and Anthropic models with `key_choice: personal`.
The admin checks whether the provider answers; each developer checks their own
key through the [provider-key API](../../docs/guide/cli-provider-keys.md).

- A provider response of 200, 401 or 403 permits setup without an organization key.
- The check sends only the configured model and a small fixed test message.
  It sends no developer credential, provider key, cookie or operator secret.
- Production uses verified HTTPS. An untrusted certificate fails before HTTP contact.
- The actual admin API requires an admin, CSRF and the mutation header; it keeps
  the selected existing classes. Anonymous and developer callers send no provider traffic.
- Redirects, wrong paths, throttling, server errors, oversized/malformed success
  responses and timeouts do not approve the model. Environment proxies are ignored.
- A timed-out check kills and reaps its owned worker.
- Successful add saves a Personal approval bound to the complete gateway definition
  and its revision. It creates no shared or developer key.
- If probing or approval storage fails, remove only the unchanged new definition.
  Keep unrelated models and any definition changed by another operator.
- If the definition changes during probing, save no approval and report the
  remaining gateway entry accurately.
- Editing a Personal model checks the provider again and preserves ownership
  only while the previously owned definition is unchanged.
- Personal setup rejects organization keys; it never reads an owner's key.
  Malformed falsy authentication fields are also refused before provider contact.

Run `python -m pytest tests/integration/test_personal_model_registration.py`.
The tests use disposable local providers and require OpenSSL for the HTTPS case.
They do not enable Personal UI, installed enrollment, routing or release selection.
