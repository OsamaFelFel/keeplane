# Manage your provider keys from the CLI

Use the [installed CLI](cli-install.md), Python 3.9+, a signed-in private Keeplane profile and a server with the
runtime provider-key endpoints. An admin must have set up the model to accept
developers' own keys before you can add one.

List the models allowed for your registered project and your saved keys:

```sh
keeplane keys list --profile ~/.config/keeplane/dev --project PROJECT_UUID
```

Each row shows `id`, `own_key_required` and `status`. Personal models report
`added` or `missing`; models using no key or a shared key report `false` and
`null`. `added` means a saved registration, including one that may need checking
again after a model changes. Listing does not test the provider or read key files;
it cannot yet report a key the provider has subsequently refused. A model that
is no longer allowed for this project disappears from the list. No key is shown.

Add or replace a key with a hidden prompt:

```sh
keeplane keys set --profile ~/.config/keeplane/dev --model coder
```

For automation, `--key-stdin` reads one key from a private pipe, with an optional
trailing newline. Avoid putting the key in command arguments, shell history or
an environment variable. Hidden input refuses to fall back to echoing the key.
The CLI sends it to Keeplane over HTTPS (HTTP is allowed on loopback) and keeps
no local copy. The server validates it before replacing the previous key.

```sh
keeplane keys status --profile ~/.config/keeplane/dev --model coder
keeplane keys remove --profile ~/.config/keeplane/dev --model coder
```

All commands recheck the profile's current account. A changed or withdrawn account
stops before key input or key management. Status reports `added` or `missing`
and `cleanup_pending`; it describes a stored registration rather than permission
to use a model. You can inspect and remove an old key after its model changes.

`cleanup_pending: true` means the registration changed but old file cleanup needs
retry. Remove withdraws the registration and retries pending deletion. After a
timeout, unavailable response or invalid mutation result, check status before
retrying: the change may already have committed. The CLI never retries an upload
automatically. Your provider key and saved CLI credentials are omitted from output.
