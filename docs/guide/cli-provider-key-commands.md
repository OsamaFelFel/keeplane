# Manage your provider keys from the CLI

Install the [CLI wheel](cli-install.md) and [sign in](cli-browser-login.md) using a
private profile. Your server must support provider-key commands. An admin must
set up the model for developers' own keys and install its protected runtime before
coding. These commands manage your key registration; release readiness remains
separate.

Add or replace a key with a hidden prompt:

```sh
keeplane keys set --profile ~/.config/keeplane/dev --model coder
```

If coding says **“Add or replace your provider key”**, use the command above with
the same model ID, then try again. You can also choose another allowed model from
`keeplane models --profile ~/.config/keeplane/dev --project PROJECT_ID`. Missing
or removed keys stop promptly; storage or policy outages remain separate errors.

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
