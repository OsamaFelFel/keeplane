# Manage your provider keys from the CLI

Use macOS or Linux, Python 3.9+, a signed-in private Keeplane profile and a server with the
runtime provider-key endpoints. An admin must have set up the model to accept
developers' own keys before you can add one. Browser sign-in and personal-model
setup/dispatch are still integration work; these commands manage registration.

Add or replace a key with a hidden prompt:

```sh
python components/cli/keeplane.py keys set --profile ~/.config/keeplane/dev --model coder
```

For automation, `--key-stdin` reads one key from a private pipe, with an optional
trailing newline. Avoid putting the key in command arguments, shell history or
an environment variable. Hidden input refuses to fall back to echoing the key.
The CLI sends it to Keeplane over HTTPS (HTTP is allowed on loopback) and keeps
no local copy. The server validates it before replacing the previous key.

```sh
python components/cli/keeplane.py keys status --profile ~/.config/keeplane/dev --model coder
python components/cli/keeplane.py keys remove --profile ~/.config/keeplane/dev --model coder
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
