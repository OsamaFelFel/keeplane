# No browser on the machine

Spec 009 ST29 "No browser on the machine" (D161, ADR 028), journey case DEV-06.
`keeplane login` signs in with the device code by itself when no browser can
open, without `--device`. Tests: `test_cli_no_browser.py`, against a controlled
sign-in server. The [integration cases](../integration/cli-admin-sign-in-cases.md)
run the same fallback against the real server.

- **NB-01 Knowing there is no browser.** There is none over SSH (`SSH_CONNECTION`,
  `SSH_CLIENT` or `SSH_TTY` set), even with a display or `BROWSER` set, because a
  browser there could never reach the CLI's own callback. On Linux and other Unix
  systems there is none without `DISPLAY` or `WAYLAND_DISPLAY`. Anywhere, there is
  none when Python can't find a browser. A `BROWSER` command the developer set is
  tried. macOS and Windows need no display variable.
- **NB-02 No browser.** `keeplane login --server …` prints "No browser can open
  here, so sign in from another device.", then the address and code, and saves a
  device sign-in. No browser is opened and no browser sign-in starts. The device
  code is never saved.
- **NB-03 The browser fails to start.** The CLI says it is opening the browser,
  then the no-browser line, then signs in with the device code. No browser code is
  exchanged.
- **NB-04 The browser raises an error.** The fallback is the same and the error's
  details are never shown.
- **NB-05 Already signed in.** A profile that is signed in is refused before a
  device code is asked for.
- **NB-06 `--device`.** Still signs in with the device code, without the
  no-browser line.
- **NB-07 No `--server`.** `login` uses the server of the profile's expired
  sign-in.
- **NB-08 No server known.** With no `--server`, no saved sign-in and no kept
  server, `login` exits 1 with "Keeplane doesn't know your server yet. Run
  `keeplane login --server <address>`." and sends nothing.
- **NB-09 Signing in again with no browser.** After an expired sign-in, answering
  yes signs in with the device code when no browser can open.
- **NB-10 After sign-out.** `logout` keeps only the server address; a plain
  `keeplane login` then signs in to that server.
- **NB-11 `--server` overrides.** With a kept server, `--server` signs in to the
  server it names instead.
- **NB-12 The browser opened but didn't finish.** When the browser sign-in times
  out or is refused, `login` exits 1 with "The sign-in in your browser didn't
  finish, so you aren't signed in. Run `keeplane login` to try again, or
  `keeplane login --device` to sign in from another device." No device code is
  asked for and nothing is saved.
- **NB-13 The kept server can't be used.** With a malformed, extra-key, oversized,
  wrong-mode or symlinked `server.json`, a plain `login` exits 1 with "Keeplane
  can't use the server address it kept for this profile. Run `keeplane login
  --server <address>`, or `keeplane forget` to remove it." and sends nothing.
- **NB-14 `--server` gets round it.** `login --server` signs in without reading
  the file, then replaces it (0600, not a link; a link's target is untouched)
  with the server it signed in to; `logout` keeps that server.
- **NB-15 `forget` removes it.** Signed out, `forget` removes the bad file
  (not a link's target), says so and exits 0; a plain `login` then says Keeplane doesn't
  know the server yet.
- **NB-16 `forget` removes a usable server.** Signed out with a usable address,
  `forget` removes it, says "Removed the saved server address. Run `keeplane
  login --server <address>` to sign in." and exits 0. With nothing saved it says
  "Keeplane has no saved sign-in or server address, so there's nothing to
  forget." and exits 0. `keeplane forget --help` says "Delete the sign-in saved
  on this machine, or, once signed out, the saved server address."
- **NB-17 A failed sign-in changes nothing.** When `login --server` fails, the
  unusable `server.json` stays exactly as it was and no credential is saved.
