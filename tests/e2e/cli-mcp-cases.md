# Resident MCP readiness control

This optional experiment uses unmodified OpenCode V2 2.0.27, with binary
SHA-256 `a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d`.
It does not select a CLI foundation or change the coding adapter.

Each resident process has a fresh private profile, loopback authentication and
a synthetic provider. The stdio MCP server withholds its tool list until the
test observes `pending`. After `/api/mcp` reports `connected`, the first coding
turn must advertise and execute the tool. No warmup model call is allowed.
A second fresh resident process repeats the control. Failed and disabled servers
must report their own status, and unauthenticated status requests must fail.

Run with the already verified Linux binary in a disposable Linux container:

```sh
KEEPLANE_OPENCODE_V2_BIN=/runtime/opencode-v2 \
  python tests/e2e/test_cli_mcp_readiness_native.py
```

Use a network-disabled container, read-only root, writable disposable `/tmp`,
read-only fixture/binary mounts and no real credentials. No downloads or model
weights are needed. Keep generated results outside Git.

The pinned [status API](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/protocol/src/groups/mcp.ts)
reports connection state. It does not expose an applied tool-registry revision;
[registration refresh](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/tool/mcp.ts)
is separately debounced. Passing these controlled first turns does not prove a
universal readiness barrier, dynamic tool-list updates, reconnects, remote MCP,
OAuth, CodeMode or child-agent inheritance.
