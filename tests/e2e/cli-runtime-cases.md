# Local CLI adapter

- **CLI-01:** A pinned real runtime reads and edits a disposable addition function
  through an authenticated loopback fixture. An existing project provider setting
  cannot divert the request. The gateway credential is absent from printed events
  and runtime profile files. An invalid credential fails without another tool call.
- **CLI-02:** Unit checks cover native errors with zero exit status, nonzero exits,
  timeouts, spawned-tool termination, detached-child pipe deadlines, profile cleanup,
  opaque credential validation, JSON-event redaction, rejected insecure endpoints and
  a mismatched runtime version.
- **CLI-03:** SIGTERM asks the pinned runtime to interrupt its session, then
  force-stops remaining owned group members after a bounded grace period,
  removes its disposable profile and exits 143. A cooperative process reaps
  its managed tool in a separate group; an uncooperative process and its grouped
  tool are force-stopped. Controls also cover a signal during process creation,
  large stdin, grouped child tools and a detached child holding output pipes. A pinned
  native runtime reaches a stalled synthetic provider before cancellation; its
  process is gone and profile removed afterward. Detached workloads and SIGKILL
  remain outside cleanup guarantees.
- **CLI-04:** Explicit instruction text and its exact content hash reach every
  parent/child model request during a real native read/edit/delegate turn. A second
  turn uses revised text without the old revision. Unselected nested guidance and
  project provider overrides are excluded. Profiles contain no gateway credential;
  invalid credentials still fail without tool calls. Unit cases reject unsafe
  paths, invalid UTF-8 and per-file/total/source-count overflows.
- **CLI-05:** Two fresh CLI processes use one private database and the same native
  session ID. The second receives the first turn's complete read/edit tool-call
  arguments and matching results, then performs another read/edit. It uses a newly
  supplied grant; an invalid grant cannot reuse the previous one. Retained DB,
  WAL, SHM and metadata contain none of those synthetic grants. Explicit history
  reset makes the old session unavailable without another provider call.
  Current instruction text/hash replaces the earlier rule without discarding
  ordinary tool history. Unknown or differently scoped sessions fail before launch.
- **KEY-09:** API keys only (Spec 009 ST30, D185; journey DEV-03). The developer's
  home already holds OpenCode sign-ins (an OpenAI subscription sign-in, a Copilot
  sign-in, an Anthropic key), settings that point OpenAI and Anthropic at a trap
  server and turn the provider plugins on, and a shell with provider keys, base
  URLs and proxies set to the trap. The pinned real runtime runs under `strace`,
  which records every address it connects or sends to. It still reads and edits
  the file, and every recorded address, on any host or port (DNS included), is
  the gateway fixture or a loopback port the runtime bound and listened on itself
  (its own local server). The trap is never contacted, no saved secret is printed,
  and every streamed request asks for usage (`stream_options.include_usage`).
  The fixture sends usage only when asked, with cached and reasoning tokens
  (10 input with 4 cached, 5 output with 2 reasoning). The turn has 3 requests,
  and its totals must be exactly 10 input and 5 output tokens for each printed
  `step_finish`, so counting either detail twice fails. The runtime prints no
  `step_finish` for the last step, so that request counts without usage.
  The unit cases KEY-01 to KEY-08 are in
  [`cli-runtime-settings-cases.md`](../unit/cli-runtime-settings-cases.md).

Run isolated checks with `python -m pytest tests/unit/test_cli_adapter.py tests/unit/test_cli_instructions.py`.
For CLI-01, install the exact runtime separately and set
`KEEPLANE_OPENCODE_V2_BIN=/absolute/path/to/opencode-v2`, then run
`python -m pytest tests/e2e/test_cli_runtime.py -m optional`.
The same file includes CLI-04. The fixture sends no outbound requests and uses only a synthetic credential.
CI runs this file in the `coding-runtime` job of `checks.yml`. That job uses
`@opencode/cli-linux-x64-baseline-musl` 2.0.27 from npm, with archive SHA-256
`19883929aff7834d777af1618a811d4d1352a46c02df3ba11aad8cafc2faf93e` and binary
SHA-256 `a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d`
(the binary the ADR 007 trials recorded). It is a musl build, so it runs in
an Alpine container with `libstdc++` and `strace`.
Use the same binary with `tests/e2e/test_cli_cancellation_native.py` for CLI-03.
Its temporary PID recorder needs an executable temporary directory; a Docker
check can use disposable `--tmpfs /tmp:mode=1777,exec` with a read-only root and
`--network none`. No model weights or cloud provider are needed.
Use the same pinned binary with `tests/e2e/test_cli_resume_native.py` for CLI-05.
The state unit cases cover private files, exact bindings, foreign-state refusal,
credential presence, history reset and inherited lock lifetime. The native lock
control kills the wrapper while its native parent is active: reset stays blocked
until the owned native group stops, then succeeds. Detached workloads, unfinished
side-effect replay and server-account binding remain outside these checks.
