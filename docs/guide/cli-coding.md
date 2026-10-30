# Code with a signed-in account

Install the [CLI wheel](cli-install.md), then use your signed-in account for a
local coding turn. This trial requires macOS or Linux, Python 3.9+, the external
OpenCode V2 2.0.27 binary, and an operator-installed protected trial gateway.
The ordinary gateway listener is insufficient: the protected listener rechecks
Keeplane identity, project and model policy on every model request. The
[installed journey](../../tests/e2e/installed-cli-cases.md) covers this flow with
a shared-key model; personal-key coding is not enabled here.

First [sign in](cli-browser-login.md). Then choose a model from
`keeplane models --profile PROFILE --project PROJECT_ID` for a registered
project, or ask the installation operator which model to use on first use.

```sh
keeplane code \
  --profile "$HOME/.config/keeplane/account" \
  --project 00000000-0000-0000-0000-000000000001 --name "Example" \
  --model coder --runtime /path/to/opencode-v2 \
  --gateway https://gateway.example.com/v1 \
  --directory /path/to/repository \
  'Fix the addition function and check the result.'
```

Use your installation's project ID, model and gateway URL. `code` checks the
current account, records project use and checks the allowed model list before
starting the runtime. If the model needs your own provider key and yours is
missing or refused, the CLI uses another allowed model and says why; see
[provider key commands](cli-provider-key-commands.md). A supplied project ID identifies requested context; it
does not prove where repository contents came from. The gateway makes the final
decision, including changes made after the CLI's initial checks.

If your organization has not added any model yet, or none is approved for the
project's data class, `code` stops before the runtime starts and sends nothing:

```text
No models are available for this project yet, so nothing was sent. Ask an admin to add a model, or approve one for this project's class, in Models and routing.
```

Settings your runtime sends with each request, such as temperature, reach the
model unchanged: Keeplane adds none of its own. If the model fails during a turn,
the turn shows the error; Keeplane does not yet move a running turn to another
model when its model is down or the task is too big for it.

```mermaid
flowchart LR
  Profile[Signed-in account] --> Check[Register project and check models]
  Check -->|no models| Stop[No models are available yet; nothing sent]
  Check --> Choice[Own key missing? Use another allowed model]
  Choice --> Local[Local coding runtime and tools]
  Local --> Gateway[Protected gateway checks every request]
  Gateway --> Model[Allowed model]
```

Only the access token reaches the local runtime. The refresh token stays in the
private account profile. Provider keys remain on the server. Reviewed instruction
files can be selected with repeatable `--instructions AGENTS.md` arguments;
repository plugins and provider overrides stay disabled.

Add `--state-dir "$HOME/.local/state/keeplane/example"` to keep private conversation
history outside the repository. Resume with that same option and `--session ID`,
using the session ID in the runtime's output. History is tied to the server,
account, project, directory, gateway, model and runtime version. Signing in again
as the same account can reuse it; a different account or project cannot. Earlier
experimental history without an account binding is refused. Start a fresh state
directory instead. History contains conversation and tool results; protect it
like repository contents.

Ctrl-C cancels the owned turn and returns 130. A timeout returns 124; termination
returns 143. Cleanup covers the owned runtime process group; detached tools and
safe resume of an unfinished turn are not guaranteed. Review file edits before
retrying: cancellation does not undo them. Finish or cancel the active command
before using its account profile elsewhere.
Sign out with `keeplane logout --profile PROFILE`; the gateway must reject
that credential on subsequent requests. Already authorized work is not recalled.

Use explicit [refresh](cli-account-profile.md) before a turn when needed;
[device sign-in](cli-device-login.md) is available when this machine has no browser.
Use [init preview](cli-migration-preview.md) to inspect existing project settings
without changing files. Migration apply and automatic routing remain separate
work. Release runtime selection and distribution checks remain open.
