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
- **NB-08 No server known.** With no `--server` and no saved sign-in, `login`
  exits 1 with "Name your Keeplane server: run `keeplane login --server
  <address>`." and sends nothing.
- **NB-09 Signing in again with no browser.** After an expired sign-in, answering
  yes signs in with the device code when no browser can open.
