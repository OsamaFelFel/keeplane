# Model registration identity

New Keeplane registrations carry the same explicit ID in the management API and
native model value. Local and cloud models keep their usual names, provider
settings and validation. A temporary shared-key verification model receives its
own unique name and ID so it cannot overwrite the original native backend.

The evaluated native compiler uses an explicit ID for a stable backend name;
name-only values include a mutable sorted position. See the pinned
[native compiler](https://github.com/agentgateway/agentgateway/blob/ea5608642b9d5c94c5baf5fd9f2f9849b808e963/crates/agentgateway/src/types/local.rs#L4488).
This field is wiring, not proof of a deployed protected listener.

Approvals still cover the complete value and revision, including the ID. Editing
or replacing a key retains an existing ID and requires the same revalidation and
fresh approval. Existing name-only definitions are not rewritten by setup,
repeat registration or key replacement. Protected enrollment must handle those
explicitly; no old fingerprint transfers to a different definition.
