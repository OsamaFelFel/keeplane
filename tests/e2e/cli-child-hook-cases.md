# Child-session request-hook control

This optional experiment uses the unchanged, hash-verified OpenCode V2 2.0.27
binary. It does not select a foundation or change the coding adapter.

A synthetic parent request invokes the native foreground `subagent` tool. The
public `context` and `http.request` hooks must observe build → explore → build,
with distinct linked sessions. Parent and child use the same selected model and
location; the backend verifies the synthetic provider credential separately.
The first-party plugin applies different temperature/top-p pairs to the two
agents. Every sent request must match a hook's body hash; other body values and
headers remain unchanged. The resumed parent must regain its own settings.

The child gets the explicit delegated prompt, rather than the parent's previous
conversation. Repository AGENTS text reaches both sessions when project discovery
is enabled. A paired control records that `OPENCODE_CONFIG_PROJECT_DISABLE=1`
also suppresses those instructions in this runtime. The current adapter uses
that flag; preserving repository instructions needs a separate integration.

Run in a disposable Linux container with a read-only root and fixture/binary
mounts, networking disabled, writable `/tmp` and no real credentials:

```sh
KEEPLANE_OPENCODE_V2_BIN=/runtime/opencode-v2 \
  python tests/e2e/test_cli_child_hooks_native.py
```

The pinned [native subagent tool](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/tool/plugin/subagent.ts)
selects the child model explicitly. The [public hooks](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/plugin/src/promise/session.ts)
are registered for the location; this does not copy a provider secret or parent
conversation into the child. Only unsigned synthetic Chat Completions and one
foreground child are covered. Explicit child-model overrides, deeper/background
children, permissions, metadata, compaction and production credentials remain
separate checks. No production plugin, sign-in or init behavior changes.

## Explicit instruction channel

A separate optional control appends one explicit text value through the public
`context` hook while project configuration remains disabled. The text is supplied
by the fixture's plugin options; no repository files are discovered or imported.
Both parent and child must receive it, while native repository AGENTS text stays
absent. Other request values, model identity and the original credential remain
checked at the actual synthetic backend.

A repository config attempts to replace that provider's address and credential.
Its trap must receive zero protected requests. A separate positive control loads
only that repository provider with discovery enabled, proving the config is
valid and the trap can observe its synthetic credential. This control is not a
permitted adapter mode.

Use the same disposable network-disabled container and pinned binary:

```sh
KEEPLANE_OPENCODE_V2_BIN=/runtime/opencode-v2 \
  python tests/e2e/test_cli_child_hooks_native.py instructions
```

This proves a narrow public instruction channel, not automatic preservation of
repository guidance. Source selection, nested precedence, file updates, saved
instruction state and untrusted-content handling need separate work. The current
adapter remains unchanged, including its AGENTS limitation.
