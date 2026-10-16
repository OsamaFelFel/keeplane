# Run a coding session with Keeplane

Use this guide with the installed trial CLI. The installation operator must
provide the wheel and checksum, a sign-in server, a protected gateway address,
an explicit project ID and an allowed model. Use macOS or Linux and Python 3.11+
for this complete sequence. Coding also needs the external OpenCode V2 2.0.27
binary; the wheel does not download it. Follow [installation](cli-install.md)
first, then activate its environment so `keeplane --help` works.

Replace these example addresses, IDs and paths with your installation's values:

```sh
KP_SERVER=https://keeplane.example
KP_GATEWAY=https://gateway.example/v1
KP_PROJECT=00000000-0000-0000-0000-000000000001
KP_MODEL=coder
KP_RUNTIME=/absolute/path/to/opencode-v2
KP_REPO=/absolute/path/to/repository
KP_PRIVATE="$HOME/.local/share/keeplane/quickstart"
mkdir -p "$KP_PRIVATE"
chmod 700 "$KP_PRIVATE"
KP_PROFILE="$KP_PRIVATE/account"
```

Keep the profile and history outside the repository. The profile stores private
plaintext credentials protected by OS file permissions. Use the server address
for account commands and the protected gateway's `/v1` address for coding;
an ordinary unprotected model listener is insufficient.
`KP_REPO` must be the Git repository root, owned by your OS user.

## Sign in and choose a model

```sh
keeplane login --server "$KP_SERVER" --profile "$KP_PROFILE"
keeplane whoami --profile "$KP_PROFILE"
keeplane register-project --profile "$KP_PROFILE" \
  --project "$KP_PROJECT" --name "My project"
keeplane models --profile "$KP_PROFILE" --project "$KP_PROJECT"
```

Sign in to your existing account and allow CLI access in the browser. `whoami`
should show that account; choose `KP_MODEL` from the returned model IDs. An empty
list means no model is currently allowed for this project. Ask the operator to
check access. Use `login --device` if this machine cannot open a browser.

## Review instructions before copying

```sh
keeplane init --preview --directory "$KP_REPO"
```

Preview changes nothing. If root `AGENTS.md` already exists, review it and skip
the copy below. Otherwise, review root `CLAUDE.md` locally, then save and confirm
one plan (use `QWEN.md` instead if that is your source):

```sh
keeplane init --preview --directory "$KP_REPO" --source CLAUDE.md \
  --plan "$KP_PRIVATE/instruction-copy.json"
keeplane init --apply "$KP_PRIVATE/instruction-copy.json" --directory "$KP_REPO"
diff -u "$KP_REPO/CLAUDE.md" "$KP_REPO/AGENTS.md"
```

The diff should be empty: a new `AGENTS.md` has the same bytes and the original
remains. Conflicting or changed instructions stop the copy; existing targets and
plans are never overwritten. This is one partial migration, not complete
onboarding. It creates no workflow defaults and imports no settings or hooks.
See [migration recovery](cli-migration-preview.md) if an outcome needs review.

## Code, review and continue

```sh
keeplane code --profile "$KP_PROFILE" \
  --project "$KP_PROJECT" --name "My project" --model "$KP_MODEL" \
  --runtime "$KP_RUNTIME" --gateway "$KP_GATEWAY" --directory "$KP_REPO" \
  --instructions AGENTS.md --state-dir "$KP_PRIVATE/history" \
  'Fix the addition function and check the result.'
```

Review the edits and run your project's tests. The runtime prints JSON events
containing `sessionID`. To continue, repeat that command with a new prompt and
`--session SESSION_ID`, replacing `SESSION_ID` with the printed value. Keep the
same profile, project, model, gateway, repository and state directory. Explicit
`--instructions AGENTS.md` reads the current reviewed text on every turn.

Ctrl-C cancels the active turn (exit 130); SIGTERM returns 143. Supported native
interruption cleans up the controlled foreground tool. Arbitrary detached work
is outside that guarantee. Cancellation does not undo edits or guarantee safe
replay of unfinished actions; review the repository before resuming. Finish or
cancel a turn before another command uses its profile. Rotate credentials
explicitly between turns when needed:

```sh
keeplane refresh --profile "$KP_PROFILE"
```

## Manage your own key and sign out

Only use these steps after the operator confirms that an installed Personal
model is enabled and verified for your gateway. Select its model ID in
`KP_MODEL`. Key registration alone does not enable dispatch or grant access.

```sh
keeplane keys set --profile "$KP_PROFILE" --model "$KP_MODEL"
keeplane keys status --profile "$KP_PROFILE" --model "$KP_MODEL"
```

Enter the provider key at the hidden prompt. `status` should say `added`. Run
`keys set` again to replace it; the server validates the new key first. Use a new
history directory when changing the coding model. Keys stay on the server;
never put one in command arguments or shell history.

```sh
keeplane keys remove --profile "$KP_PROFILE" --model "$KP_MODEL"
keeplane keys status --profile "$KP_PROFILE" --model "$KP_MODEL"
keeplane logout --profile "$KP_PROFILE"
```

Status should now say `missing`. Logout withdraws the CLI credential pair and
removes the local credential; it does not delete conversation history. If a key
change or logout is uncertain, follow [key recovery](cli-provider-key-commands.md)
or [account recovery](cli-account-profile.md) before retrying. This remains a
bounded integration trial; complete onboarding, automatic refresh and release
runtime selection are separate work.
