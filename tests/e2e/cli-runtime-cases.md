# Local CLI adapter

- **CLI-01:** A pinned real runtime reads and edits a disposable addition function
  through an authenticated loopback fixture. An existing project provider setting
  cannot divert the request. The gateway credential is absent from printed events
  and runtime profile files. An invalid credential fails without another tool call.
- **CLI-02:** Unit checks cover native errors with zero exit status, nonzero exits,
  timeouts, spawned-tool termination, profile cleanup, credential redaction, rejected insecure endpoints and
  a mismatched runtime version.

Run the isolated checks with `python -m pytest tests/unit/test_cli_adapter.py`.
For CLI-01, install the exact runtime separately and set
`KEEPLANE_OPENCODE_V2_BIN=/absolute/path/to/opencode-v2`, then run
`python -m pytest tests/e2e/test_cli_runtime.py -m live`.
The fixture sends no outbound requests and uses only a synthetic credential.
