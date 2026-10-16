# Prepare the CLI sign-in trial

The trial reuses Keeplane accounts: sign in through the browser and choose
**Continue** to grant CLI access. Password changes, disabled accounts and global
sign-out withdraw access. CLI logout revokes that CLI's pair; refresh rotates it.
The default preview keeps the optional issuer disabled and uninstalled.

## Local app image

Start the normal [local preview](local-preview.md) first so the UI is built.
With Docker running, build the explicit trial target from the repository root:

```sh
docker build --platform linux/amd64 \
  --file components/control-plane/Dockerfile --target cli-auth-trial \
  --tag keeplane-cli-trial:local .
```

This installs only the hash-pinned Linux musl Python 3.13 wheel graph. Original
wheel notices remain installed; build-only Python installers are removed.
The ordinary build still selects `preview` without the optional dependencies.

After adding an approved keyless/shared model, select the image with the managed
runtime launcher:

```sh
python3 deploy/local/up.py --runtime-model MODEL_ID \
  --runtime-app-image keeplane-cli-trial:local
```

The launcher migrates and registers the fixed clients. Keep the same private
runtime directory to preserve accounts, keys and approvals. Use the returned
server address when signing in. The server's `PUBLIC_ORIGIN` must match the
browser and CLI address; use HTTPS except for a configured loopback installation.
Keep your [CLI profile](cli-account-profile.md) outside Git.

## Python development server

An existing Python 3.12 development environment can install the optional graph
instead. Keep its database, signing secret, first-admin password and built UI:

```sh
python -m pip install -r components/control-plane/requirements-account-api.txt
python -m pip install --require-hashes --no-deps \
  -r components/control-plane/requirements-cli-auth.txt
python components/control-plane/manage.py migrate --noinput
python components/control-plane/manage.py register_cli_client
```

Start that server with `KEEPLANE_CLI_OAUTH_ENABLED=1`. The registration command
refuses a changed fixed client; it does not silently repair one. After migration,
turning acceptance off retains the token models. Removing the dependency requires
a planned schema rollback.

Use the image locally for the approved integration trial. Publishing or selecting
a release still requires complete native source, notice and packaging review.
This guide does not approve a distributable image or complete the coding journey.
