# Expired sign-in against the real sign-in server

Spec 009 ST29 (D190, ADR 028), journey cases DEV-07 and DEV-05. These run the
real CLI over HTTP against Django and Django OAuth Toolkit, after a real
browser sign-in. A stand-in gateway records any request it gets, and a stand-in
runtime records each coding turn.

- **EXP-INT-01 Expired, then signed in again.** The CLI access token is aged past
  its expiry in the sign-in server's database.
  - In a script, `keeplane code` exits 1 with "Your Keeplane sign-in has expired,
    so nothing was sent. Run `keeplane login` to sign in again." The server gets
    one account check, the gateway gets nothing and the runtime never starts.
  - In a terminal, answering yes signs in again through the browser with the
    saved server. The new credential is for the same account and the server
    accepts it. Answering yes again starts the task once.
- **EXP-INT-02 Signed out.** After `keeplane logout`, `keeplane code` exits 1
  with "You're signed out of Keeplane, so nothing was sent. Run `keeplane login`
  to sign in." Neither the server nor the gateway gets any request.

Run with the CLI sign-in packages installed (see
[CLI sign-in](cli-oauth-identity-cases.md)):
`KEEPLANE_CLI_OAUTH_ENABLED=1 python -m pytest -m "" tests/integration/test_cli_sign_in_again.py`.
The cases with no sign-in packages are in the
[unit cases](../unit/cli-sign-in-again-cases.md).
