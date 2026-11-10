# CLI sign-in on the server

Developers sign in to the Keeplane CLI with their existing Keeplane accounts:
the CLI opens the browser, they sign in and choose **Continue** to allow CLI
access. Without a browser the CLI shows a code to enter in a browser elsewhere.
Password changes, disabled accounts and global sign-out withdraw access. CLI
logout revokes that CLI's credential pair; refresh rotates it. Sign-ins last 8
hours (ADR 028).

## Local preview

CLI sign-in is on in the [local preview](local-preview.md). `python3
deploy/local/up.py` builds the app image with the sign-in packages, turns
sign-in on, registers the fixed browser and device CLI clients and starts the
[guarded model gateway](guarded-runtime.md). There is nothing else to set up:

```sh
python3 deploy/local/up.py
keeplane login --server http://127.0.0.1:3000 --profile "$HOME/.config/keeplane/account"
```

The server's `PUBLIC_ORIGIN` must match the address the browser and CLI use;
the launcher sets it from `--port`. Use HTTPS except on a loopback address.
Keep your [CLI profile](cli-account-profile.md) outside Git. See
[browser sign-in](cli-browser-login.md) and [device sign-in](cli-device-login.md).

The image's sign-in packages are installed from
`components/control-plane/requirements-cli-auth.txt`: Django OAuth Toolkit
3.4.1 and its dependencies, as hash-pinned Linux musl Python 3.13 wheels. Their
original wheel notices stay installed and build-only Python installers are
removed. The image is built on your computer from those wheels. The
[source and notice obligations](../../components/control-plane/licenses/cli-auth-trial.md)
apply before anyone redistributes an image or bundle that contains them.
Shipping them, `jwcrypto` (LGPL) included, in a published image or bundle still
waits for the owner's decision (governance issue #85, question 1); locally built
previews are unaffected.

## Python development server

An existing Python development environment can install the same packages
instead. Keep its database, signing secret, first-admin password and built UI:

```sh
python -m pip install -r components/control-plane/requirements-account-api.txt
python -m pip install --require-hashes --no-deps \
  -r components/control-plane/requirements-cli-auth.txt
python components/control-plane/manage.py migrate --noinput
python components/control-plane/manage.py register_cli_client
python components/control-plane/manage.py register_cli_client --device
```

Start that server with `KEEPLANE_CLI_OAUTH_ENABLED=1`. The registration command
refuses a changed fixed client; it does not silently repair one. After migration,
turning sign-in off keeps the token tables. Removing the packages needs a
planned schema rollback.

## Shared-database and Kubernetes installs

CLI sign-in works the same on a shared PostgreSQL database with several app
copies behind one address. Give every copy the same signing secret, database
and `PUBLIC_ORIGIN`, and set `KEEPLANE_GATEWAY_PUBLIC_URL` to the gateway
address developers' CLIs use: the managed gateway's protected listener, or
the developer listener of your own gateway. A sign-in started on one copy can
finish on another. The
[release journey cases](../../tests/e2e/developer-journey-release-cases.md)
check this with the developer journey, DEV-01 to DEV-08, on two copies with
each kind of gateway.

Sign-ins, codes waiting for approval and refresh tokens are kept in the
database, so restarting the app, PostgreSQL or the gateway signs nobody out. While
the app or PostgreSQL is down, the CLI tells developers Keeplane isn't available
and saves nothing half done: a browser sign-in is started again, a device sign-in
keeps waiting, a refresh keeps the current sign-in, and a coding task stops
before its next model call. A customer-run gateway set to `failureMode: deny`
refuses model calls while Keeplane's check can't run. The
[restart and outage cases](../../tests/e2e/sign-in-restart-outage-cases.md) run
each of these on PostgreSQL with a customer-run gateway.

The PostgreSQL image targets with sign-in are `postgres-cli-auth-trial` and
`postgres-cli-auth-detection`; see [PostgreSQL accounts](postgres-accounts.md)
and the [Kubernetes installation reference](kubernetes-installation-reference.md).
