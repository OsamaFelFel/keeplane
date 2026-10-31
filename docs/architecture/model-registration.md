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

## Removal

Removing a model Keeplane added is one settings transaction around the gateway
step. Keeplane deletes the approval and writes its settings-change record
first, then asks the gateway to delete the definition, and commits only after
the gateway confirms. If the record write fails, the gateway is never asked. If
the gateway refuses, the transaction rolls back and nothing is recorded.

The commit itself can still fail after the gateway deletion. Keeplane then
writes the same definition back and binds the unchanged approval to its new
gateway revision, without a settings-change record, as it does when a key
replacement is undone. If the write back fails, the admin is asked to check
Models. Developers' personal keys for that model are bound to the old revision
and need checking again after such a write back. A shared key file is deleted
only after the removal commits.

Removing setup for a model added outside Keeplane never contacts the gateway.
The settings transaction holds the settings lock while the gateway answers, so
other settings changes wait for that call.
