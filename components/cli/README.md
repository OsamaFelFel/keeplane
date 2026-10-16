# Use the Keeplane CLI

Start with the installed `keeplane` command:

1. [Install the CLI wheel](../../docs/guide/cli-install.md). It contains Keeplane's
   commands and instruction hook; install the coding runtime separately.
2. [Preview an existing project](../../docs/guide/cli-migration-preview.md) with
   `keeplane init --preview`. This reads supported instructions and settings;
   it does not change or migrate files. Preview requires Python 3.11+.
3. [Sign in through your browser](../../docs/guide/cli-browser-login.md), or use
   [a device code](../../docs/guide/cli-device-login.md). Check your account with
   `keeplane whoami`.
4. [Register a project and list its models](../../docs/guide/cli-project-commands.md).
   Use the explicit project ID supplied for your work.
5. [Run a coding turn and resume it](../../docs/guide/cli-coding.md) with
   `keeplane code`. Select reviewed instruction files explicitly and keep history
   outside the repository.
6. [Refresh or sign out](../../docs/guide/cli-account-profile.md) with
   `keeplane refresh` or `keeplane logout`, using the same private profile.

These commands need macOS or Linux and Python 3.9+ unless noted above. Sign-in
needs an operator-configured trial server. Coding also needs the exact external
OpenCode V2 **2.0.27** binary and the installation's protected gateway URL.
The gateway checks current account, project and model policy on every request;
provider keys stay on the server. The ordinary gateway listener is insufficient.

The [installed journey](../../tests/e2e/installed-cli-cases.md) covers real Django
sign-in, managed gateway installation, native read/edit tools, refreshed
credentials, account/project-bound resume and logout with synthetic accounts.
This remains an integration trial: release runtime selection and distribution
checks are open. Migration apply and automatic refresh are not implemented.
[Personal key commands](../../docs/guide/cli-provider-key-commands.md) manage
server-held registrations; personal-key coding is not enabled by this journey.
Cancellation stops the owned runtime process group but cannot guarantee cleanup
of detached tools or safe continuation of an unfinished turn. Review edits
before retrying.

## Low-level adapter prototype

Use the standalone adapter below only for an operator-controlled integration
experiment. It does not use the signed-in account profile or send the project
context supplied by `keeplane code`.

This experimental adapter connects OpenCode V2 **2.0.27** to an explicitly
configured protected gateway. The standalone command below exercises the coding
loop with an operator-supplied test credential. It does not select
the runtime for the release. No runtime binary is bundled or downloaded.

```mermaid
flowchart LR
  Adapter[Local adapter] --> Runtime[Local coding runtime]
  Runtime --> Gateway[Protected gateway]
  Gateway --> Model[Configured model]
```

Use macOS or Linux, Python 3.9+, an independently installed exact runtime binary and a gateway
with an OpenAI-compatible API and tool-capable model. Obtain a test gateway
credential from the installation operator. This is a Keeplane gateway credential,
not a cloud provider key. Provider keys stay on the server.

From the repository root, run:

```sh
python3 components/cli/opencode_adapter.py \
  --runtime /absolute/path/to/opencode-v2 \
  --gateway https://keeplane.example/v1 \
  --model registered-coder \
  --directory /absolute/path/to/project \
  --instructions AGENTS.md \
  'Fix the failing addition test.'
```

Enter the gateway credential at the hidden prompt. Automation can supply
`KEEPLANE_GATEWAY_GRANT` through its secret environment; never type the value
into a command or commit it. HTTP is accepted only for a loopback test gateway.
This prototype accepts credentials made of letters, digits, `.`, `_`, `~` and `-`.

The adapter prints the runtime's JSON events when the turn ends. Review its edits and run the
project's tests. A denied request or native error exits unsuccessfully; a timeout
exits with 124; Ctrl+C exits with 130; SIGTERM during a turn exits with 143.
All three ask the pinned runtime to interrupt its session, allowing up to four
seconds for native tool cleanup before force-killing the owned process group.
Parent reaping is bounded by a further second; inherited output pipes cannot
extend cleanup. Independently detached or unmanaged workloads remain outside
that boundary; this prototype is not a sandbox. An unresponsive runtime can
still leave tools in separate groups when force-kill is required.
SIGTERM during process creation is deferred until the adapter owns the child.
The version probe retains its separate ten-second limit. The prior SIGTERM handler
is restored when the CLI's coding invocation ends. SIGKILL cannot run cleanup.
`--timeout 600` gives a slow turn ten minutes. A failed turn can
leave edits, so inspect the diff before retrying. There is no direct-provider fallback.

Each turn uses a temporary profile and excludes existing runtime configuration,
credentials and extensions. `--instructions AGENTS.md` explicitly includes a
reviewed UTF-8 file directly in `--directory`; repeat the option for more files.
The adapter snapshots their bytes, labels them with SHA-256 hashes, and adds that
text through its own context hook for parent and child requests. A later turn
reads a fresh snapshot. Files are limited to 32 KiB each, 64 KiB total and eight
sources; symlinks, special files, duplicates and paths in other directories are
refused. The final encoded runtime configuration is capped at 120 KiB, including
JSON escaping. File contents are instructions, never executable configuration.

There is no automatic discovery: without `--instructions`, repository guidance
is still omitted. Ancestor and nested directory rules need a separate scoped
integration; this option does not flatten them into every request. Project
provider settings, plugins, hooks and credential stores remain excluded. The
[paired native control](../../tests/e2e/cli-child-hook-cases.md) explains why
enabling all project configuration would be unsafe.
The profile is removed when the invocation ends. To keep a completed session,
add `--state-dir /absolute/private/keeplane-session` outside the repository.
Its parent directory must already exist. Keeplane creates a private state
directory or accepts an empty private one; existing vendor profiles and databases
are refused. The runtime's JSON events contain the session ID. Repeat the same
command with `--session SESSION_ID` and the same state directory to continue it.
Supply a current gateway credential again; no saved credential authorizes resume.
Repeat `--instructions` to use the current reviewed text.

Only the runtime database is retained; HOME, configuration, caches and temporary
files remain disposable. State is bound to the canonical working directory,
gateway API, model and exact runtime version. Changed bindings, unsafe files or
stored runtime credentials are refused. One owned lock serializes its use.
Resume also requires an existing idle native session in that directory and model;
unknown IDs fail before provider contact. This check uses the pinned runtime's
database metadata because its native `--session` option can create a missing ID.
The standalone adapter binds only local OS-user history. The installed
`keeplane code` command also binds the issuer, current account and project;
neither path proves repository provenance.

To remove all saved history from that state while keeping its binding and lock:

```sh
python3 components/cli/session_state.py --discard /absolute/private/keeplane-session
```

The next invocation can start a new session. An active state cannot be reset.
Do not unlink its lock to bypass that check. If initial creation was interrupted
and the state is rejected, inspect the owned directory and choose a fresh one.
After an interrupted coding turn, review edits before continuing; this slice
proves completed text/tool turns, not safe replay of unfinished side effects or
attachments from discarded caches. Built-in tool permission prompts remain enabled.
This is not a sandbox or proof of project provenance. Use the installed commands
above for sign-in and authorized-model discovery. Automatic routing, migration
apply and release distribution remain separate work.
