# Installed CLI journey

This optional test installs a prebuilt Keeplane wheel into a clean private venv.
It uses actual Django accounts, browser consent, credential rotation, model
registration, managed enrollment and the pinned native gateway/runtime. The only
model is a deterministic local provider that requests real read/edit tools.

| Case | Required result |
| --- | --- |
| ICJ-01 | Offline wheel install/help and `init --preview`; instruction contents stay private and repository bytes stay unchanged. |
| ICJ-02 | Existing account signs in through the real CSRF-protected browser flow; current identity and allowed catalog agree. |
| ICJ-03 | Protected coding reads/edits the file using the server-held shared key; explicit instruction hash reaches the provider. |
| ICJ-04 | Refresh withdraws old access; a fresh process resumes the same native session with preserved assistant/tool history and the new credential. |
| ICJ-05 | Two independently allowed projects/accounts cannot reuse each other's local session history; denied attempts make zero provider calls. |
| ICJ-06 | Logout removes local credentials and prevents both protected requests and further refresh; retained history contains no OAuth pair bytes. |
| ICJ-07 | Separate client namespace has no installation volume, cannot reach loopback admin or use raw operator routes; wrong TLS trust fails. |

Use an immutable composed checkout containing the browser issuer, stable model
registration, actual managed installer and `installed_runtime` bootstrap. Its
five CLI fixture files must exactly match the test checkout. Supply a cached
native-capable Django image with the pinned optional OAuth trial dependencies;
this test does not build images, download wheels or fetch models.

```sh
export KEEPLANE_INSTALLED_CLI_REQUIRED=1
export KEEPLANE_INSTALLED_CLI_SOURCE=/absolute/path/to/frozen-checkout
export KEEPLANE_INSTALLED_CLI_IMAGE=sha256:your-cached-native-and-oauth-image
export KEEPLANE_INSTALLED_CLI_WHEEL=/absolute/path/to/keeplane_cli-0.0.0-py3-none-any.whl
export KEEPLANE_INSTALLED_CLI_WHEEL_SHA256=your-reviewed-wheel-sha256
export KEEPLANE_OPENCODE_V2_BIN=/absolute/path/to/pinned/opencode
python -m pytest -q -m optional tests/e2e/test_installed_cli_journey.py
```

Docker Compose and OpenSSL are prerequisites. The fixture uses an internal
network, read-only container roots and UID 65532, with owned disposable writable
volumes/tmpfs. Only the public synthetic CA reaches the developer container;
`SSL_CERT_FILE` keeps normal certificate verification enabled in Python and the
native runtime. A test-only TLS relay forwards bytes without authorizing requests.
Safe reports and private failure diagnostics stay in pytest's temporary directory;
cleanup runs in `finally`, and any cleanup failure fails the test.

This covers browser sign-in and shared-key coding. Device mode, cancellation,
destructive migration, personal-key dispatch, external TLS deployment and release
runtime selection are separate checks. Project registration here repeats the
explicit fixture seed; it does not invent repository identity or init defaults.

The separate `test_installed_cli_cancellation.py` case opts into two additional
checks on a known saved session. It sends SIGINT/SIGTERM only after the provider
has answered and a real foreground native shell child has written its owned PID
barrier. Exit codes must be 130/143 within five seconds, with no native/tool PID or
temporary runtime profile left behind. Process states, including zombies, are
recorded before cleanup on failure. Each signal is followed by real credential
rotation and a fresh process resuming the completed assistant/tool history.
Interrupted-call visibility is reported, without requiring a particular treatment
of unfinished work. Arbitrary detached or background processes are outside this
controlled foreground-tool check.
