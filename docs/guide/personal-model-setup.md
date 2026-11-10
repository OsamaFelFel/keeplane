# Set up a model for each developer's own key

In **Models and routing**, choose **Add model**, select OpenAI or Anthropic,
enter the upstream model ID and choose **Each developer adds their own key**.
Choose approved classes if they are enabled, then add the model. No shared key
is needed. **Edit** keeps the Personal choice when you save its classes. Its
key choices follow what can be saved: a model with no key can move to each
developer's own key; a shared key can't be chosen in Edit, because Edit has no
step to enter one. Edit greys out the choices it can't save and says: "To use a
choice that's greyed out, remove the model and add it again with that key
choice."
Installed Personal coding remains separate work.

This choice needs Keeplane's own gateway. When Keeplane uses a customer-run
gateway (`GATEWAY_MODE=existing`), Add, Edit and Set up refuse it with HTTP 422
and "Keeplane can't pass developers' own keys to a gateway it doesn't run yet, so
use No key for this model. Nothing was saved." before saving anything or
changing the gateway. A model set up this way earlier can then only move to No
key (`key_choice: none`, with any class change) or be removed; see
[provider keys on a customer-run gateway](gateway-configuration.md#provider-keys-on-a-customer-run-gateway).

The same setup is available through the admin API. Use an existing admin browser
session and the normal CSRF and
`X-Keeplane-Action: 1` mutation headers.

Send `POST /api/models` with:

```json
{
  "name": "personal-coder",
  "model": "YOUR_UPSTREAM_MODEL_ID",
  "source": "openai",
  "key_choice": "personal",
  "approved_classes": []
}
```

Use `anthropic` for an Anthropic model. If data classes are on, choose existing
approved classes. Do not submit a shared key. Keeplane registers a keyless
definition, checks the configured provider over verified HTTPS, then saves its
approval. An authentication-required response confirms provider reachability;
it does not verify a developer's key or whether that account can use the model.

To recheck or change approved classes, send `POST /api/models/MODEL_ID/setup`
with `key_choice: personal` and the classes. Each developer then uses the
[CLI key commands](cli-provider-key-commands.md) to add their own key. The server
checks it against the current definition; changing the definition requires a
fresh key check. Registration alone does not enroll the model for installed coding.

A failed add removes only its unchanged new gateway entry. If that cannot be
confirmed, the error tells you to check Models. Existing approvals remain intact
when an edit fails. No provider response body or key appears in the error.
