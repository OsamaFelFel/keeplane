# Admins in the CLI and sign-out against the real sign-in server

Spec 009 ST29 "An admin signs in", "No browser on the machine" and "Sign out"
(D188, D161, ADR 028, ADR 018); journey cases DEV-05, DEV-06 and DEV-08. Tests:
`test_cli_admin_sign_in.py`. The real CLI talks HTTP to Django and Django OAuth
Toolkit. A controlled browser signs in and allows access, a stand-in gateway
records every request it gets and a stand-in runtime records each coding turn.
One model, `coder`, is approved.

- **ADM-INT-01 to 04 Admins work like developers.** The first admin and a
  developer each sign in with `keeplane login`, once through the browser and once
  on a machine with no browser (the device code, with no `--device`). For each:
  - the profile is saved for that account and sign-in client;
  - `whoami` shows the account's role;
  - `register-project` records the repo's project;
  - `models` lists only `coder`;
  - `use elsewhere` is refused with "elsewhere isn't allowed for this project.
    Nothing was saved. Choose one that `keeplane models` lists.";
  - `code --model elsewhere` is refused and the runtime never starts;
  - `code --model coder` runs one turn.
- **ADM-INT-05 and 06 Sign out.** After a browser or a device sign-in,
  `keeplane logout` revokes the sign-in at the server and keeps only the server
  address in the profile. Then `code`, `models` and `usage` each exit 1 with
  "You're signed out of Keeplane, so nothing was sent. Run `keeplane login` to
  sign in."; `whoami` and `refresh` exit 1 with "You're signed out of Keeplane.
  Run `keeplane login` to sign in." Neither the server nor the gateway gets any
  request and the runtime never starts. A plain `keeplane login`, with no
  `--server`, signs in to the kept server, and then `code` runs.

Run with the CLI sign-in packages installed (see
[CLI sign-in](cli-oauth-identity-cases.md)):
`KEEPLANE_CLI_OAUTH_ENABLED=1 python -m pytest -m "" tests/integration/test_cli_admin_sign_in.py`.
The cases with no sign-in packages are in the
[no-browser unit cases](../unit/cli-no-browser-cases.md).
