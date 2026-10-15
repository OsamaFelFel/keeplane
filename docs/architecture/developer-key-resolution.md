# Resolve a stored provider key

The internal `store.resolve(model_id, expected_definition_fingerprint=...)`
returns an owner-scoped `ResolvedProviderKey` for a trusted server consumer.
The fingerprint must come from the server's current full model definition.
`repr()` and `str()` hide the key; only `for_provider()` returns its plaintext.
Never log, serialize or send that value to a client. There is no HTTP key-read
route or inference integration.

```mermaid
flowchart LR
    caller[Trusted server caller] --> owner[Lock active owner]
    owner --> binding[Check personal approval and full current fingerprint]
    binding --> file[Read private active file]
    file --> result[Redacted result for provider transport]
```

Resolution owns a database transaction and rejects an enclosing transaction.
It locks the same owner as replacement and removal, then locks current approval
and checks the fresh gateway definition. The stored validated binding must
match. Withdrawn owners, missing keys, changed definitions and unavailable
storage all return `Provider key is unavailable`, without underlying details.
Pending cleanup files are never selected.

The configured directory and its ancestors are operator-controlled. The final
directory and file are opened without following symlinks; the file is opened
relative to that directory descriptor. Both must belong to the app UID. Only
private directory modes 0700/0500 and file modes 0600/0400 are accepted. Files
must be regular, have one hard link and contain 12–512 non-space ASCII bytes,
matching the [provider validator](provider-key-validation.md). Reads are bounded
and nonblocking; FIFOs and other special files are rejected.

This check is not a dispatch permit or a revocable lease. The caller still
authenticates the request, checks project/model access and proves the actual
selected provider destination. Approval or key changes affect later resolutions;
bytes already returned remain in trusted caller memory. The database binds a
file reference and definition, not a digest of its contents. Another process
with the same UID can alter managed files; this service does not attest those
bytes or authorize arbitrary native model policies. Only the validator's narrow
supported definition format is accepted.

Run the [read-safety cases](../../tests/integration/developer-key-resolution-cases.md)
with `python -m pytest tests/integration/test_developer_key_resolution.py`.
