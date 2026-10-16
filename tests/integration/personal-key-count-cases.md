# Admin developer-key counts

Run `python -m pytest tests/integration/test_personal_key_count.py`.
These checks use isolated Django records and a fake gateway registry. No key
file or provider is read; the count describes current-bound registrations.

| Case | Action | Expected result |
| --- | --- | --- |
| DK-COUNT-01 | Mix active developer/admin keys with inactive, changed-definition, unbound, withdrawn and other-model records. | Only the two current-bound active owners count. Changing approval or withdrawing an owner changes the count. Catalog setup fields remain unchanged. |
| DK-COUNT-02 | List current and changed personal models. | Only current personal models carry a count; owner identities, key names and fingerprints are absent. |
| DK-COUNT-03 | Fetch Models as an admin, developer and anonymous user, then interrupt count storage. | Admin sees the count; other callers are denied. Storage failure gives 503 rather than an invented zero. |

The React `MO-UI-COUNT` case shows zero, singular and plural counts using the
Models canvas wording; shared models show no developer count. Runtime dispatch,
public key writes and provider health are outside these checks.
