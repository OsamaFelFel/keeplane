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
readback is the confirmation, as before.

Keeplane reads every copy in parallel, again on each pass, half a second
apart. The whole check has one 5-second deadline across all passes and
copies, and no read outlives it, so a hung copy can't keep the admin waiting
past the dialog's 10-second limit. A copy confirms when it reads the same
definition and revision as the approval (for a removal, when it no longer
lists the model). A file-owned preview model comes from the gateway's mounted
file, not the shared store, so a copy confirms it when it answers and holds no
store entry that would replace the file's definition.

Each refusal answers `503` with a `title` and the `error` text the dialog
shows; `[N] of [M]` counts the copies.

- **Adding a model** (local, runner or cloud): after the gateway address
  confirms and the model answers, every copy must confirm. If one doesn't,
  nothing is approved and the new definition is removed (with its shared key
  file): "[Model] wasn't added", "Not every gateway copy confirmed it: [N] of
  [M] did. Nothing was saved. Check the gateway and try again." If the removal
  fails too: "… It may still be listed in the gateway, but it gets no work.
  Check Models."
- **Editing setup** (a new definition, wider classes, or a key choice that
  gives access): the same readback runs before anything is saved. If a copy
  doesn't confirm: "[Model] wasn't changed", "Not every gateway copy confirmed
  the change: [N] of [M] did. Nothing was saved, and its earlier setup stays.
  Check the gateway and try again." A changed definition never matches the
  earlier approval, so it stays unavailable until every copy confirms.
- **Replacing a shared key**: if a copy doesn't read the new definition, the
  previous key and definition go back: "Not every gateway copy confirmed the
  new key: [N] of [M] did. Nothing was saved, and the earlier key stays. Check
  the gateway and try again." If they can't go back: "… The model may need
  attention. Check Models."
- **Withdrawing access** on an unchanged definition (fewer classes, or moving
  from no key to each developer's own key): saved at once with no copy
  readback. Every copy's checks read the saved setup, so it applies on all
  copies when saved; a copy that is down never holds it back.
- **Removing a model Keeplane added**: the approval is removed first, so every
  copy's checks refuse the model before the admin is answered, and the shared
  key file is deleted. Keeplane then waits for every copy to stop listing the
  model. If one still lists it, the removal stands: "[Model] was removed",
  "Developers can't use it, but [N] of [M] gateway copies still list it. Check
  the gateway." This also holds when the database reports a failed commit
  that was in fact kept. Removing a model added outside Keeplane reads no copy.

An unusable `GATEWAY_COPY_URLS` (any bad entry) is logged as a warning when
the app starts and on each refused change. Adding a model or widening access
is then refused with "[Model] wasn't added" (or "wasn't changed") and "Keeplane
can't check every gateway copy because the gateway copy list in its settings
isn't valid. Nothing was saved. Ask whoever installed Keeplane to fix it."
Withdrawing access still applies, and a removal still stands, with "Developers
can't use it, but Keeplane can't check every gateway copy …".

Only the changed model is read and written. Other models keep their
definitions, approvals and access whatever a copy answers. The
[copy cases](../../tests/unit/gateway-copy-cases.md) cover these rules with
fake copies that lag, stay stale, hang or are down.
