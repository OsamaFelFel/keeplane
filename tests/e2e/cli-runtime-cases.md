# Local CLI adapter

- **CLI-01:** A pinned real runtime reads and edits a disposable addition function
  through an authenticated loopback fixture. An existing project provider setting
  cannot divert the request. The gateway credential is absent from printed events
  and runtime profile files. An invalid credential fails without another tool call.
- **CLI-02:** Unit checks cover native errors with zero exit status, nonzero exits,
  timeouts, spawned-tool termination, detached-child pipe deadlines, profile cleanup,
  opaque credential validation, JSON-event redaction, rejected insecure endpoints and
  a mismatched runtime version.
- **CLI-03:** SIGTERM stops the owned runtime process group, removes its disposable
  profile and exits 143. Controls cover a signal during process creation, large
  stdin, grouped child tools and a detached child holding output pipes. A pinned
  native runtime reaches a stalled synthetic provider before cancellation; its
  process is gone and profile removed afterward. Detached workloads and SIGKILL
  remain outside cleanup guarantees.

Run the isolated checks with `python -m pytest tests/unit/test_cli_adapter.py`.
For CLI-01, install the exact runtime separately and set
`KEEPLANE_OPENCODE_V2_BIN=/absolute/path/to/opencode-v2`, then run
`python -m pytest tests/e2e/test_cli_runtime.py -m live`.
The fixture sends no outbound requests and uses only a synthetic credential.
Use the same binary with `tests/e2e/test_cli_cancellation_native.py` for CLI-03.
Its temporary PID recorder needs an executable temporary directory; a Docker
check can use disposable `--tmpfs /tmp:mode=1777,exec` with a read-only root and
`--network none`. No model weights or cloud provider are needed.
