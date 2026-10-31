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

A model that an admin chose for a [complexity level](complexity-levels.md) is
refused with `409` and the levels that use it, before the gateway is read. The
same check runs again under the settings lock inside `DjangoModelCatalog.remove`.
The settings transaction holds the settings lock while the gateway answers, so
other settings changes wait for that call.

## Every gateway copy

A gateway can run as several serving copies that share one model store, such
as the managed chart's two replicas. A write through the gateway address
reaches each copy on its own schedule. An operator lists every copy's own
management address in `GATEWAY_COPY_URLS` (comma-separated `http` or `https`
origins, at most 32, no credentials or paths). The app reads each copy with
the gateway's management key; it never writes to a copy or asks it for a model
answer. Without the setting, the gateway address is the only copy and its own
readback is the confirmation, as before. A list with any unusable entry
confirms nothing, so every change below is refused until it is fixed.

- **Adding a model** (local, runner or cloud): after the gateway address
  confirms and the model answers, every copy must read the same definition and
  revision. Keeplane waits up to about five seconds. If a copy doesn't
  confirm, nothing is approved, the new definition is removed again (with its
  shared key file), and the admin reads "Not every gateway copy confirmed the
  model. N of M gateway copies confirmed it." followed by what was undone.
- **Editing setup** (a new definition, a new key choice or more classes): the
  same readback runs before anything is saved. If a copy doesn't confirm,
  nothing is saved and the model keeps its earlier setup. A changed
  definition never matches the earlier approval, so it stays unavailable
  until the admin sets it up again and every copy confirms.
- **Replacing a shared key**: if a copy doesn't read the new definition, the
  previous key and definition go back, as when the new key fails.
- **Narrowing classes** on an unchanged definition only withdraws access.
  Every copy's checks read the saved setup, so it applies on all copies when
  it is saved and needs no copy readback; a copy that is down never holds it
  back.
- **Removing a model Keeplane added**: the approval is removed first, so every
  copy's checks refuse the model before the admin is answered, and the shared
  key file is deleted. Keeplane then waits for every copy to stop listing the
  model. If one still lists it, the removal is kept and the admin reads "Model
  removed from Keeplane, so developers can't use it, but not every gateway
  copy confirmed it's gone. N of M gateway copies confirmed it. Check the
  gateway." Removing a model added outside Keeplane reads no copy.

Only the changed model is read and written. Other models keep their
definitions, approvals and access whatever a copy answers. The
[copy cases](../../tests/unit/gateway-copy-cases.md) cover these rules with
fake copies that lag, stay stale or are down.
