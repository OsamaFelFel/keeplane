# Run a coding session with Keeplane

Use this guide with the installed trial CLI. The installation operator must
provide the wheel and checksum, a sign-in server and a protected gateway
address. Your repo needs no setup in Keeplane. Use macOS or Linux and Python
3.11+ for this complete sequence. Coding also needs the external OpenCode V2
2.0.27 binary as `opencode` on your `PATH`; the wheel does not download it.
Follow [installation](cli-install.md) first, then activate its environment so
`keeplane --help` works.

Replace these example addresses and paths with your installation's values:

```sh
KP_SERVER=https://keeplane.example
KP_GATEWAY=https://gateway.example/v1
KP_PRIVATE="$HOME/.local/share/keeplane/quickstart"
mkdir -p "$KP_PRIVATE"
chmod 700 "$KP_PRIVATE"
cd /absolute/path/to/repository
```

Every command below uses your private profile in `~/.config/keeplane/account`,
which stores plaintext credentials protected by OS file permissions; pass
`--profile PATH` to use another. Keep history outside the repository. Use the
server address for sign-in and the protected gateway's `/v1` address for
coding; an ordinary unprotected model listener is insufficient. The server
now gives a signed-in CLI the gateway address its installer set, but this CLI
version doesn't use it yet, so pass `--gateway` to `keeplane code`. With `--state-dir`, the session history records the
gateway address, and a later turn on that history, such as a resumed session,
must use the same one. On a Kubernetes installation with the chart's Ingress, both are
on Keeplane's one address: `KP_SERVER=https://<host>` and
`KP_GATEWAY=https://<host>/v1` (see
[what to give developers](kubernetes-installation-reference.md#how-developers-reach-protected-models)).
On the Docker preview with [guarded model access](guarded-runtime.md) it is
`http://127.0.0.1:5000/v1` unless the launcher was given another port.
These two addresses are the only ones the CLI and the coding runtime it starts
need to reach, so the sequence also works on an isolated network; see
[Developers' computers](outbound-connections.md#developers-computers).

## Sign in and see your models

```sh
keeplane login --server "$KP_SERVER"
keeplane whoami
keeplane models
```

Sign in to your existing account and allow CLI access in the browser. `whoami`
should show that account. `models` lists the models this repo may use; Keeplane
works out the repo's project from its `origin` remote, as
[project commands](cli-project-commands.md#how-a-repo-becomes-a-project)
explains. An empty list means no model is currently allowed for this project.
Ask the operator to check access. Use `login --device` if this machine cannot
open a browser.

## Review instructions before copying

```sh
keeplane init --preview
```

Preview changes nothing. If root `AGENTS.md` already exists, review it and skip
the copy below. Otherwise, review root `CLAUDE.md` locally, then save and confirm
one plan (use `QWEN.md` instead if that is your source):

```sh
keeplane init --preview --source CLAUDE.md \
  --plan "$KP_PRIVATE/instruction-copy.json"
keeplane init --apply "$KP_PRIVATE/instruction-copy.json"
diff -u CLAUDE.md AGENTS.md
```

The diff should be empty: a new `AGENTS.md` has the same bytes and the original
remains. Conflicting or changed instructions stop the copy; existing targets and
plans are never overwritten. This is one partial migration, not complete
onboarding. It creates no workflow defaults and imports no settings or hooks.
See [migration recovery](cli-migration-preview.md) if an outcome needs review.

## Code, review and continue

```sh
keeplane code --gateway "$KP_GATEWAY" \
  --instructions AGENTS.md --state-dir "$KP_PRIVATE/history" \
  'Fix the addition function and check the result.'
```

`code` names the model for the task before it starts and, once the turn has
finished, the model that answered. To switch this repo to another model from
`keeplane models`, run `keeplane use <model>`; `keeplane use --auto` goes back to
Keeplane's pick. `--model MODEL` chooses one for a single turn.

Review the edits and run your project's tests. The runtime prints JSON events
containing `sessionID`. To continue, repeat that command with a new prompt and
`--session SESSION_ID`, replacing `SESSION_ID` with the printed value. Keep the
same profile, model, gateway, repository and state directory. Explicit
`--instructions AGENTS.md` reads the current reviewed text on every turn.

Ctrl-C cancels the active turn (exit 130); SIGTERM returns 143. Supported native
interruption cleans up the controlled foreground tool. Arbitrary detached work
is outside that guarantee. Cancellation does not undo edits or guarantee safe
replay of unfinished actions; review the repository before resuming. Finish or
cancel a turn before another command uses its profile. Rotate credentials
explicitly between turns when needed:

```sh
keeplane refresh
```

## Manage your own key and sign out

Only use these steps after the operator confirms that an installed Personal
model is enabled and verified for your gateway. Set `KP_MODEL` to its model ID
and pass `--model "$KP_MODEL"` to `code`. Key registration alone does not enable dispatch or grant access.

```sh
keeplane keys set --model "$KP_MODEL"
keeplane keys status --model "$KP_MODEL"
```

Enter the provider key at the hidden prompt. `status` should say `added`. Run
`keys set` again to replace it; the server validates the new key first. Use a new
history directory when changing the coding model. Keys stay on the server;
never put one in command arguments or shell history.

```sh
keeplane keys remove --model "$KP_MODEL"
keeplane keys status --model "$KP_MODEL"
keeplane logout
```

Status should now say `missing`. Logout withdraws the CLI credential pair and
removes the local credential; it does not delete conversation history. If a key
change or logout is uncertain, follow [key recovery](cli-provider-key-commands.md)
or [account recovery](cli-account-profile.md) before retrying. This remains a
bounded integration trial; complete onboarding, automatic refresh and release
runtime selection are separate work.
