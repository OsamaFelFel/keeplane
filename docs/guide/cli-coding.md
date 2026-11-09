# Code with a signed-in account

Install the [CLI wheel](cli-install.md), then use your signed-in account for a
local coding turn. This trial requires macOS or Linux, Python 3.9+, the external
OpenCode V2 2.0.27 binary, and an operator-installed protected trial gateway.
The ordinary gateway listener is insufficient: the protected listener rechecks
Keeplane identity, project and model policy on every model request. The
[installed journey](../../tests/e2e/installed-cli-cases.md) covers this flow with
a shared-key model; personal-key coding is not enabled here.

First [sign in](cli-browser-login.md). Then go to any Git repo and run:

```sh
cd /path/to/repository
keeplane code --gateway https://gateway.example.com/v1 \
  'Fix the addition function and check the result.'
```

The repo needs no setup in Keeplane. `code` works out everything else:

| What | Where it comes from | Override |
| --- | --- | --- |
| Account | The profile in `~/.config/keeplane/account` (or `$XDG_CONFIG_HOME/keeplane/account`) | `--profile PATH` |
| Project | The repo's `origin` remote, or an ID saved in the repo's Git folder; see [how a repo becomes a project](cli-project-commands.md#how-a-repo-becomes-a-project) | `--project ID --name NAME` |
| Model | The model Keeplane picks for this project, which `code` names before it starts | `--model MODEL` |
| Coding runtime | `"runtime"` in your [settings file](#the-settings-file), then `opencode` on your `PATH` | `--runtime PATH` |
| Gateway | The address saved in your profile when you signed in | `--gateway URL` |
| Folder | The folder you run it in | `--directory PATH` |

Today the server doesn't tell the CLI its gateway address yet, so pass
`--gateway` with the address your admin gave you. Without it, `code` sends
nothing and says:

```text
Keeplane doesn't know your gateway address yet, so nothing was sent. Pass --gateway with the address your admin gave you, ending in /v1.
```

Once your Keeplane server gives the address at sign-in, sign in again and
`keeplane code 'task'` needs no options at all.

On a Kubernetes installation with the chart's Ingress, the gateway URL is
Keeplane's own address followed by `/v1`, such as
`https://keeplane.example.com/v1` (see
[how developers reach protected models](kubernetes-installation-reference.md#how-developers-reach-protected-models)).
On the Docker preview it is `http://127.0.0.1:5000/v1`.

Without `--model`, `code` asks the server which allowed model the task goes to
and prints, for example, `Using coder for this task, chosen by Keeplane. Pass
--model to choose another.` If none of the project's models can be used right
now, it sends nothing and says so. `code` checks the current account, records
that you use the project, and checks the allowed model list before starting the
runtime. Until an admin sets the repo's data class on the Projects page, the
repo can use every model your organization has approved. If the model needs
your own provider key and yours is missing or refused, the CLI uses another
allowed model and says why; see
[provider key commands](cli-provider-key-commands.md). The project ID is the
context the CLI asks for; it does not prove where repository contents came
from. The gateway makes the final decision, including changes made after the
CLI's initial checks.

### When your sign-in has expired

A sign-in lasts 8 hours. When the Keeplane server or the gateway says it has
expired, `code` sends nothing more. The server is checked before the runtime
starts, so usually nothing has been sent at all. In a terminal it offers to sign
you in again:

```text
Your Keeplane sign-in has expired, so nothing was sent. Sign in again now? [Y/n]
```

Press Enter (or type `y`) to sign in again with the same server, the same way
as last time: through the browser, or with a code if you used `login --device`.
Then `code` asks before it starts the task:

```text
Signed in. Start the task now? [Y/n]
```

If the gateway refused the sign-in part-way through a task, the steps that had
already run stay on screen and the message says "so nothing more was sent". Saying
yes then starts the task again from the beginning, so review any edits first.
Answering `n` to either question stops with:

```text
Run `keeplane login` to sign in again.
```

In a script, or whenever the CLI isn't talking to a terminal, there is no
question. `code` exits with status 1 and prints:

```text
Your Keeplane sign-in has expired, so nothing was sent. Run `keeplane login` to sign in again.
```

Other commands, such as `keeplane models` and `keeplane whoami`, print the same
message and exit 1; only `code` offers to sign in again. `keeplane login`
replaces the expired sign-in.

### When you're signed out

After `keeplane logout`, or before you have ever signed in, `code`, `models`,
`keys`, `whoami`, `register-project`, `refresh` and `logout` send nothing and
exit 1 with:

```text
You're signed out of Keeplane, so nothing was sent. Run `keeplane login` to sign in.
```

There is no offer to sign in here; run `keeplane login` when you want to.

```mermaid
flowchart LR
  Code[keeplane code] --> Saved{Signed in?}
  Saved -->|no| Out[Signed out; nothing sent]
  Saved -->|yes| Server[Server checks the sign-in]
  Server -->|401| Expired[Expired; nothing sent]
  Server -->|ok| Runtime[Runtime and gateway]
  Runtime -->|gateway 401| Expired2[Expired; nothing more sent]
  Expired --> Terminal{Terminal?}
  Expired2 --> Terminal
  Terminal -->|no| Exit[Exit 1: run keeplane login]
  Terminal -->|yes| Offer[Sign in again, then ask to start]
```

### The coding runtime

`code` runs OpenCode V2 **2.0.27** and refuses any other version. It looks for
it in `--runtime`, then in the settings file, then as `opencode` on your
`PATH`. If it finds none, or finds another version, it starts nothing and says
how to fix it:

```text
Keeplane needs OpenCode V2 2.0.27, and /usr/local/bin/opencode is another version or doesn't run. Install 2.0.27, then put it on your PATH, pass --runtime PATH, or set "runtime" in your Keeplane settings file.
```

### The settings file

Your CLI settings live outside every repo, in
`~/.config/keeplane/settings.json` (or `$XDG_CONFIG_HOME/keeplane/settings.json`).
To keep the runtime somewhere other than your `PATH`, save its full path there:

```json
{"runtime": "/opt/opencode-2.0.27/bin/opencode"}
```

Only you may be able to change the file (for example `chmod 600`), because
`code` runs the program it names. Keys Keeplane doesn't know are ignored.
Server and gateway addresses are not kept here; they stay in your profile.

If your organization has not added any model yet, or none is approved for the
project's data class, `code` stops before the runtime starts and sends nothing:

```text
No models are available for this project yet, so nothing was sent. Ask an admin to add a model, or approve one for this project's class, in Models and routing.
```

If the requested model is approved for the project but can't be used right now,
for example because it is not installed or its shared provider key is gone,
`code` also stops before the runtime starts and sends nothing to any other model:

```text
coder is approved for this project but can't be used right now, so nothing was sent. Choose another model allowed for this project, or ask an admin to check it in Models and routing.
```

The project's data class always applies. Model or provider settings in the
repository's own runtime configuration, and runtime environment variables, are
not loaded, so they cannot send a task to a model outside the class.

Settings your runtime sends with each request, such as temperature, reach the
model unchanged: Keeplane adds none of its own.

`keeplane code` has no web search and no web fetch: the model cannot search
the web or open a web page during a turn, even if your shell holds a search
provider key: the runtime's built-in web
tools and hosted search providers are turned off, so a turn never sends its
content to a service your admin did not set up. The only places a turn reaches
are your Keeplane server and the gateway; see
[Developers' computers](outbound-connections.md#developers-computers).

### When the model is down or the task is too big

If the model answers with a server error (5xx), cannot be reached, times out, or says it is busy
(429) before any of its answer has reached you, the gateway sends the same
request to the same model twice more. Keeplane never moves the task to another
model on its own. If the model is still down, the turn stops and `code` prints
the runtime's error followed by:

```text
coder is unavailable right now, so this task stopped. Wait and try again, or run it with another model allowed for this project using --model: general, local.
```

Run the same `code` command again later, or with one of the listed models in
`--model`. The list is checked for you: only models set up in Keeplane, allowed
for the project's class and with a usable key. If no other model is allowed
for the project, `code` prints instead:

```text
coder is unavailable right now and no other model is allowed for this project. Wait and try again, or ask your admin to set up another model.
```

When the model refuses a task as too big for its context, nothing is retried
and `code` prints:

```text
This task is too big for coder's context, so it stopped. Run it with another model allowed for this project using --model: large.
```

If no other model is allowed for the project, it prints instead:

```text
This task is too big for coder's context and no other model is allowed for this project. Make the task smaller, or ask your admin to set up a model with a larger context.
```

Once part of an answer has started to arrive, a failure is shown as it is and
nothing is sent again. An older Keeplane server cannot list the alternatives;
the message then points to `keeplane models` instead. The missing-key case
above is different: there `code` does switch to another allowed model and says
so before it starts.

```mermaid
flowchart LR
  Repo[Repo in this folder] --> Project[Project from origin remote or saved ID]
  Project --> Profile[Signed-in account]
  Profile --> Check[Register project and check models]
  Check -->|no models| Stop[No models are available yet; nothing sent]
  Check -->|model can't be used now| Stop2[Model can't be used right now; nothing sent]
  Check --> Choice[Own key missing? Use another allowed model]
  Choice --> Local[Local coding runtime and tools]
  Local --> Gateway[Protected gateway checks every request]
  Gateway --> Model[Allowed model]
  Model -->|5xx, timeout or 429 before the answer starts| Retry[Same model, up to two more tries]
  Retry -->|still down| Tell[Stop: wait, or choose a listed model]
  Model -->|too big for its context| Tell
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
Sign out with `keeplane logout`; the gateway must reject
that credential on subsequent requests, and the CLI then [sends
nothing](#when-youre-signed-out) until you sign in again. Already authorized work is not recalled.

Use explicit [refresh](cli-account-profile.md) before a turn when needed;
[device sign-in](cli-device-login.md) is available when this machine has no browser.
Use [init preview](cli-migration-preview.md) to inspect existing project settings
without changing files. Release runtime selection and distribution checks remain open.
