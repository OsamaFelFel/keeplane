# Internal developer-key storage

`DjangoDeveloperKeyStore(owner_id, directory, validate_key=...)` keeps one key per
account and model. `put(model_id, value)` adds or replaces it; `remove(model_id)`
withdraws it; `status(model_id)` reports `added` or `missing` and
`cleanup_pending`. Results contain no key, filename or other account's state.
This service has no HTTP route, CLI command or inference integration.

The caller must supply a real server validator. It receives the owner ID, model
ID and submitted key, and must return exactly `True` after checking current model
eligibility and the provider. A refusal or failed check preserves the old key.
The service provides no permissive default validator.

Key files use the existing local gateway store: random names, a private directory
(0700), files readable only by their owner (0600), and container UID/GID 65532.
The database stores only ownership and file basenames. This reuses local-trial
storage; it supplies neither encryption nor shared replica storage.

Each write owns its database commit and rejects an enclosing transaction.
Replacement commits the new reference before deleting the old file. Removal
clears the active reference before deleting its file. Failed cleanup retains a
pending reference for retry; another mutation cannot accumulate more old files.
If cleanup's database check fails after commit, the error explicitly says the
state changed. Retry status before deciding what to do next.

Files and the database cannot commit together. A failed commit attempts to remove
the new file. A simultaneous unlink failure, or a process kill between file
creation and commit, can leave an unreferenced file requiring operator recovery.
There is no automatic orphan collector in this slice.

Before public submission or dispatch, follow-up work must bind validation to the
current provider definition (and recheck after edits), support the developer-key
model choice, and handle refused keys and account removal. Currently ownership
records prevent account deletion until their files and records are removed; the
existing account-removal API does not perform that cleanup. Do not wire public
admission until this prerequisite is resolved. There is no key-read API here.

Run the [isolated storage cases](../../tests/integration/test_developer_key_store.py)
with `python -m pytest tests/integration/test_developer_key_store.py`. They use
synthetic keys and validators; they do not claim live provider validation.
