# Expired sign-in and signed-out cases

Spec 009 ST29 "The sign-in has expired" and "Sign out" (D190, ADR 028). Journey
cases DEV-07 and DEV-05. The wording was decided by the associate product owner.

A 401 from the Keeplane server or from the gateway means the sign-in has
expired. The server is checked before the coding runtime starts, so a 401 there
means nothing reached the gateway.

- **EXP-01 In a script.** `keeplane code` exits 1 with "Your Keeplane sign-in has
  expired, so nothing was sent. Run `keeplane login` to sign in again." The only
  request is the account check; the runtime never starts and the saved
  credential is kept.
- **EXP-02 In a terminal, yes and yes.** The CLI asks "Your Keeplane sign-in has
  expired, so nothing was sent. Sign in again now? [Y/n]". Enter (or y, yes, in
  any case) removes the expired credential, signs in through the browser with the saved
  server, then asks "Signed in. Start the task now? [Y/n]". Only after the
  second yes does the task start, with the new credential.
- **EXP-03 Declining to sign in.** n, no, any other answer, or no answer at all
  exits 1 with "Run `keeplane login` to sign in again." Nothing is sent and the
  expired credential stays, so a later script still says it has expired.
- **EXP-04 Declining to start.** After signing in, n exits 1 with "You're signed
  in. The task wasn't started, so nothing was sent. Run it again when you're
  ready." and the task does not start.
- **EXP-04b Declining to continue.** When earlier steps had gone out, the line
  is "You're signed in. The task wasn't continued, so nothing more was sent. Run
  it again when you're ready."
- **EXP-05 Device sign-in.** A profile saved by `login --device` signs in again
  with the device code, not the browser.
- **EXP-06 The gateway refuses part-way.** When the runtime already showed a
  step and then the gateway said 401, the earlier output is still shown, the
  message says "so nothing more was sent", and no other request follows (not
  even the list of other models).
- **EXP-07 The gateway refuses the first step.** The message says "so nothing was
  sent".
- **EXP-08 Offered once.** If the task is refused again after signing in again,
  the CLI reports it and does not offer a second time.
- **EXP-09 Other commands.** Only `code` offers to sign in again; the others
  exit 1 after the account check alone. `whoami`, `models` and `keys status`
  print "Your Keeplane sign-in has expired. Run `keeplane login` to sign in
  again." `keys set` and `keys remove` print "Your Keeplane sign-in has expired.
  Nothing was saved. Run `keeplane login` to sign in again." `register-project`
  prints the script message.
- **EXP-10 `keeplane login` after expiry.** It replaces the expired credential,
  as the message says.
- **EXP-11 A current sign-in.** `keeplane login` still refuses a profile the
  server accepts, and opens no browser.
- **EXP-12 Server unreachable.** `keeplane login` keeps the saved credential; it
  is removed only when the server says 401.
- **EXP-13 Only the gateway refused it.** The server still accepts the sign-in.
  On yes the CLI asks the server to revoke it, then signs in again; "This
  profile is signed in" never appears, and the task runs with the new
  credential.
- **EXP-14 Cancelling the new sign-in.** The old credential was removed when the
  developer said yes, so Ctrl-C during the new sign-in (exit 130) leaves them
  signed out, and the next `code` says so.
- **EXP-15 Server unreachable when signing in again.** Signing in again stops
  with the connection error and keeps the saved credential.
- **OUT-01 Signed out.** After `keeplane logout` only the server address is
  kept, nothing is sent and the command exits 1. `code`, `models`, `usage`,
  `keys` and `register-project` say "You're signed out of Keeplane, so nothing
  was sent. Run `keeplane login` to sign in." `whoami` and `refresh` say "You're
  signed out of Keeplane. Run `keeplane login` to sign in." `use` says "You're
  signed out of Keeplane, so nothing was saved. Run `keeplane login` to sign in."
- **OUT-03 Logout again.** `logout` when already signed out prints "You're
  already signed out of Keeplane.", sends nothing and exits 0.
- **OUT-02 Never signed in.** With no profile at all the message is the same,
  there is no offer even in a terminal, and no profile folder is created.

Run `python -m pytest tests/unit/test_cli_sign_in_again.py`. The real sign-in
server with an expired token is covered by the
[integration case](../integration/cli-sign-in-again-cases.md).
