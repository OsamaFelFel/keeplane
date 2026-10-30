# Manage your provider keys from the CLI

Install the [CLI wheel](cli-install.md) and [sign in](cli-browser-login.md) using a
private profile. Your server must support provider-key commands. An admin must
set up the model for developers' own keys and install its protected runtime before
coding. These commands manage your key registration; release readiness remains
separate.

List the models allowed for your registered project and your saved keys:

```sh
keeplane keys list --profile ~/.config/keeplane/dev --project PROJECT_UUID
```

Each row shows `id`, `own_key_required` and `status`. Personal models report
`added`, `missing` or `refused`; models using no key or a shared key report `false` and
`null`. `added` means a saved registration, including one that may need checking
again after a model changes. `refused` is the last confirmed result of an explicit
saved-key check. Listing does not test the provider or read key files. A model that
is no longer allowed for this project disappears from the list. No key is shown.

Add or replace a key with a hidden prompt:

```sh
keeplane keys set --profile ~/.config/keeplane/dev --model coder
```

If you run `keeplane code` with a model that needs your own key and you have not
added one, removed it, or it was refused, the task goes to another model you are
allowed to use for that project. Before the runtime starts, the CLI says why:

```text
No provider key is added for coder; using general instead. Add one with `keeplane keys set --model coder`.
```

A refused key says “The provider refused your key …”, and a key saved before the
admin changed the model says it was saved for an earlier model setup; both ask you
to replace it. Keeplane picks the first model, by model ID, that you could use for
that project right now: it is set up and installed, allowed for the project's data
class, and its shared key or your own key is available. A model that only exists in
the gateway is never picked. The gateway still checks the chosen model on every
request. Add or replace your key with the command above to use the original model
again on your next task.

If no other allowed model exists, coding stops before the runtime starts with
**“Add or replace your provider key: … no other allowed model is available for this
project.”** Storage or policy outages remain separate errors. If you resume a saved
session (`--session`) and the model changed, the CLI refuses to mix models; start a
new session or add your key first. With an older server that cannot choose a model,
coding keeps your model and the gateway stops it with “Add or replace your provider
key”.

For automation, `--key-stdin` reads one key from a private pipe, with an optional
trailing newline. Avoid putting the key in command arguments, shell history or
an environment variable. Hidden input refuses to fall back to echoing the key.
The CLI sends it to Keeplane over HTTPS (HTTP is allowed on loopback) and keeps
no local copy. The server validates it before replacing the previous key.

```sh
keeplane keys status --profile ~/.config/keeplane/dev --model coder
keeplane keys check --profile ~/.config/keeplane/dev --model coder
keeplane keys remove --profile ~/.config/keeplane/dev --model coder
```

All commands recheck the profile's current account. A changed or withdrawn account
stops before key input or key management. Status reports `added`, `missing` or `refused`
and `cleanup_pending`; it describes a stored registration rather than permission
to use a model. You can inspect and remove an old key after its model changes.

Use `check` when you need to verify the saved key again. Keeplane makes one
bounded provider request without sending the key back to your machine. A provider
refusal records `refused` and stops that key from being used. A successful check
restores `added`; replacing the key also clears an earlier refusal. An unavailable
provider or changed model returns an error and leaves the previous status intact.
A rejected replacement never changes the old key's status. `list` and `status`
make no provider requests, so they do not promise the key still works now.

`cleanup_pending: true` means the registration changed but old file cleanup needs
retry. Remove withdraws the registration and retries pending deletion. After a
timeout, unavailable response or invalid mutation result, check status before
retrying: the change may already have committed. The CLI never retries an upload
automatically. Your provider key and saved CLI credentials are omitted from output.
