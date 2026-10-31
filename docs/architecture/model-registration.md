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
replacement is undone. Before writing back, Keeplane reads the approval again:
if it is gone, the commit was kept despite the error and the removal is
reported as done; if it changed, nothing is written back and the admin is
asked to check Models. If the write back or its readback fails, the admin is
also asked to check Models. Developers' personal keys for that model are bound
to the old revision, so the admin is told they need checking again. A shared
key file is deleted only after the removal commits. If another request already
removed the setup, the removal answers "Model setup not found".

A gateway that deletes the model but loses its answer, for example to a
timeout, still leaves the approval in place while the model is gone; Keeplane
cannot tell this from a refusal. The leftover approval matches no gateway
definition, so it grants nothing and is not listed.

Removing setup for a model added outside Keeplane never contacts the gateway.
The settings transaction holds the settings lock while the gateway answers, so
other settings changes wait for that call.
