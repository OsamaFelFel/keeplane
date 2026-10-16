# Current instructions and resumed sessions

This optional pinned OpenCode V2 2.0.27 control observes the public request hook;
it does not choose how Keeplane should preserve or update instructions.

One explicit owned file contains rule A, then B, then C. The fixture reads at
most 129 bytes per context hook and accepts only those synthetic revisions.
A parent and its foreground child receive A initially and B on later turns of
the same sessions. After restarting the resident process, resumed sessions
receive C. Restarting without the hook supplies none of the earlier rules.
Ordinary earlier conversation and the same parent/child IDs must still replay.

The synthetic rules are absent from the public saved active-context response.
This does not prove they are absent from every internal log or store. The hook
reapplies current text on this tested path; it does not recover a historical rule
from the saved session. Native instruction baselines/deltas are a separate
[mechanism](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/session/instruction-state.ts),
prepared before the later [request hook](https://github.com/anomalyco/opencode/blob/1f4d07a4a519185955ae8ab2ea3607805509e386/packages/core/src/session/model-request.ts).

Run with the same hash-verified binary in a disposable Linux container: no
network, read-only root/fixture/binary, writable private `/tmp`, no real keys.

```sh
KEEPLANE_OPENCODE_V2_BIN=/runtime/opencode-v2 \
  python tests/e2e/test_cli_instruction_revisions_native.py
```

Only idle-turn updates, foreground children and synthetic Chat Completions are
covered. Concurrent edits, compaction, rollback and other protocols remain
separate. No repository discovery, production plugin or instruction-policy
change is introduced. Generated evidence stays outside Git.
