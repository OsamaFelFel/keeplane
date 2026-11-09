# Get started with the Keeplane CLI

This guide takes a developer from nothing to a first coding task on the local
preview: sign in, choose a model, code in your repo, see your usage and sign
out. Your repo needs no setup in Keeplane. The same steps are checked
automatically as DEV-01 to DEV-05 in the
[developer journey cases](../../tests/e2e/developer-journey-cases.md).

## Before you start

- The preview is running (`python3 deploy/local/up.py`; see
  [Run Keeplane locally](local-preview.md)). It prints the server address,
  `http://127.0.0.1:3000`, and the guarded gateway, `http://127.0.0.1:5000/v1`.
- An admin has created your developer account in **Users** and approved at
  least one model for Public data in **Models and routing**.
- The CLI is installed and `keeplane --help` works; see
  [Install the Keeplane CLI](cli-install.md). From a source checkout,
  `python3 components/cli/keeplane.py` works the same way.
- OpenCode V2 2.0.27 is on your `PATH` as `opencode`. The CLI doesn't download
  it. Use macOS or Linux.

## 1. Sign in

```sh
keeplane login --server http://127.0.0.1:3000
keeplane whoami
```

The browser opens Keeplane's sign-in page. Sign in with your account and choose
**Continue** to allow CLI access. The CLI says `Signed in to Keeplane.` and
`whoami` shows your account. With no browser on this computer, add `--device`
and enter the printed code in a browser elsewhere
([device sign-in](cli-device-login.md)).

Your sign-in is kept in the private profile `~/.config/keeplane/account`
(`--profile PATH` uses another). At sign-in the server also gives the CLI its
gateway address, so you never type it.

## 2. Choose a model

In your repo:

```sh
cd /path/to/your/repo
keeplane models
keeplane use <model>
```

`models` lists only the models allowed for this repo's project and marks the
one your next task uses. Keeplane works out the project from the repo's
`origin` remote. `models`, `use` and `code` record the repo, so it shows
on the admin's **Projects** page as not set up, with your name
([how a repo becomes a project](cli-project-commands.md#how-a-repo-becomes-a-project)).
An empty list means no model is allowed for this project yet; ask your admin.

`use <model>` makes this repo's next tasks use that model: the CLI says
`This repo's next tasks use <model>.` `keeplane use --auto` goes back to
Keeplane's pick, and `keeplane code --model <model>` picks one for a single
task ([choose the model](cli-coding.md#choose-the-model)).

## 3. Code

```sh
keeplane code "Make the failing test pass"
```

The task goes to the model through Keeplane's guarded gateway. The CLI says
which model the task uses, prints the runtime's answer and file changes, and
ends with `Answered by <model>.` Review the edits (`git diff`) and run your
tests. The runtime prints JSON events containing `sessionID`; to continue the
same conversation, see [coding](cli-coding.md).

Ctrl-C cancels the task. Cancelling doesn't undo edits already made, so review
the repo before you run it again.

## 4. See your usage

```sh
keeplane usage
```

You see your own tokens per model for today and this month. A local model shows
`—` for cost; a cloud model shows a cost estimated from the provider's list
price. Nobody else's tasks are in your totals. See [your own usage](cli-usage.md).

## 5. Sign out

```sh
keeplane logout
```

The CLI withdraws its sign-in on the server and removes the local credential.
After that, `keeplane code` and `keeplane models` say
`You're signed out of Keeplane, so nothing was sent. Run keeplane login to sign in.`
and send nothing. Sign in again with `keeplane login`.

## Next steps

- Reuse instructions you already have in `CLAUDE.md` or `QWEN.md`: preview and
  copy them to `AGENTS.md` with `keeplane init`
  ([migration preview](cli-migration-preview.md)).
- Use your own provider key for a model that needs one: `keeplane keys list`,
  then [provider key commands](cli-provider-key-commands.md).
- Set a temperature or maximum output per model in your settings file
  ([coding](cli-coding.md)).
- Recover a profile or sign-in: [account profile](cli-account-profile.md).

## Other installations

On another Keeplane server, use its address with `login --server`. You need
only the server address. When you sign in, the server gives the CLI the
protected gateway's `/v1` address its installer set, and the CLI saves it in
your profile for `keeplane code`; an ordinary unprotected model listener is
insufficient. If `code` says Keeplane doesn't know your gateway address yet,
the server gave none when you signed in. If you signed in with an older CLI
version, run `keeplane refresh` to save the server's address; otherwise ask
the operator for it and pass it as `--gateway`, which also overrides the saved
one. With `--state-dir`, the session history records the gateway address, and
a later turn on that history, such as a resumed session, must use the same one.
On a Kubernetes installation with the chart's Ingress, both are on Keeplane's
one address: `KP_SERVER=https://<host>` and the gateway `https://<host>/v1`
(see [what to give developers](kubernetes-installation-reference.md#how-developers-reach-protected-models)).
These two addresses are the only ones the CLI and the coding runtime it starts
need to reach, so the steps also work on an isolated network; see
[Developers' computers](outbound-connections.md#developers-computers).
