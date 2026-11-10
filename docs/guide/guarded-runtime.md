# Guarded model access

The local preview serves a guarded model endpoint on loopback port 5000 for the
Keeplane CLI. `python3 deploy/local/up.py` starts it on every start, with CLI
sign-in, and needs no extra options (ADR 028). Approve a model in **Models and
routing** and the model enroller enrols it within a few seconds:
keyless/shared models and Personal OpenAI/Anthropic models are supported.
Only newly registered models with a stable native ID can be enrolled; existing
name-only models are not rewritten. Developers
[add their own key](cli-provider-key-commands.md) before using a Personal model;
keys remain on the server.

Use `--runtime-port 5001` to change the host port. The coding endpoint is
`http://127.0.0.1:5000/v1` (or the chosen port), printed at start-up. The CLI
saves it when you sign in, and the coding command's `--gateway` overrides it.
Sign in through
[the CLI browser flow](cli-browser-login.md). Provider keys remain on the
server. The caller supplies its current credential and registered
`X-Keeplane-Project-ID`; the project header is not proof of repository or
content identity. Until a model is approved the endpoint serves nothing.

On every start the launcher stops the old managed gateway before preparing
disabled enrollment, starts a new process, migrates the app, registers the
fixed browser and device CLI clients and checks the app again. A failed step
stops that managed gateway. Fix the reported setup problem, then rerun
`python3 deploy/local/up.py`. Existing accounts, API models and keys remain
stored. Do not edit the generated manifest to make a failed check pass.

The launcher then starts the private model enroller (`model-enroller`). Its
first pass enrols every model saved in Models and routing, and start-up prints
its report. It then keeps the protected checks in step with the models saved
there, without restarting the gateway or the app:

- A model you add is enrolled within a few seconds.
- A developer's own provider key needs no enrollment: a new or replaced one
  applies to their next request. A shared key is different (see the next
  point).
- A model added outside Keeplane, straight into the gateway, shows as not set
  up and gets no work until you set it up. Setting it up enrols it within a
  few seconds, as adding does.
- A model you remove is refused as soon as you remove it. Removing a model
  added outside Keeplane takes it out of Keeplane only: it stays in your
  gateway and shows again as added outside Keeplane, getting no work.
- A model whose destination changes in the gateway, outside Keeplane, is
  refused at once and shows as not set up; set it up again to use it. As with
  an edit, the new setup takes effect about 3 minutes and 16 seconds after the
  destination changed, once every request sent under the old destination has
  finished its retries.
- A model you edit (or a shared key you replace) is refused at once. Its new
  setup is enrolled after about 3 minutes and 16 seconds, once every request
  that started under the old setup has finished its retries. While a change
  waits, every protected model can be refused if the gateway's own state moved;
  the enroller's log says "A model change is waiting". When the hold ends the
  log reports the settled state, for example `Protected access is ready: 1
  model is enrolled.` or `No model is enrolled for protected access.`, even
  when the hold only removed models left from before.

The enroller has no port, reads models through a read-only database connection
and is the only service that writes the private installation volume after
enrollment; the app's copy of that volume stays read-only. Of the app's account
volume it mounts only the `database` folder, read-only, so it can't read the
signing secret or anything else kept there. Check it with
`docker compose -f compose.yaml -f deploy/local/runtime.yaml logs model-enroller`.
If it reports that enrollment did not complete, protected access stays refused
and it tries again every 2 seconds. To stop automatic changes, stop the
`model-enroller` service. Access then stays as last enrolled until a model
changes; after that, protected models are refused until you start it again or
rerun the launcher.

Earlier previews kept the database at `/state/keeplane.sqlite3` (and before
that in `accounts.sqlite3` and `model-approvals.sqlite3`). Before the first
release Keeplane doesn't carry trial data forward, so this preview starts a
fresh database in the folder, with only the first admin, and leaves the earlier
files unused and unchanged; start-up prints a notice when it finds them. To
reset the preview fully, stop everything, including the enroller, remove every
container still using the account volume (an earlier preview's stopped
containers hold it too), remove the volume, then start the preview again (see
[earlier preview data](local-preview.md#earlier-preview-data)):

```sh
docker compose -f compose.yaml -f deploy/local/runtime.yaml --profile runtime down --remove-orphans
docker ps -aq --filter volume=keeplane-accounts-trial_model-approvals | xargs -r docker rm -f
docker volume rm keeplane-accounts-trial_model-approvals
```

Changing the gateway configuration itself needs the launcher again so a fresh
gateway verifies it. Personal key changes apply to the next request.
Normal provider failures can recover on the next request; endpoint eviction or
wiring changes still require fresh enrollment.
After upgrading to the new health signature, rerun the launcher once to enroll
a fresh gateway. Existing manifests are not accepted automatically.

The protected route retries a model that is down twice before returning the
error, and never switches the model ([how it works](../architecture/runtime-authorization.md#a-model-that-is-down-or-too-small)).
This changes the generated route: an earlier installation keeps working without
the retry until you rerun the launcher once after upgrading.

This covers the managed local preview only. Virtual/fallback models,
customer gateways, Kubernetes, replicas and a release image are outside its
current scope (Kubernetes has its own enroller; see the
[installation reference](kubernetes-installation-reference.md)). The live
preview checks start the preview with `python3 deploy/local/up.py` and run the
enroller against the real gateway image, including a CLI sign-in with zero and
then one approved model ([cases](../../tests/e2e/preview-sign-in-live-cases.md)).
See the
[operator contract](../architecture/runtime-authorization.md#managed-operator-contract)
for enrollment fields, private callbacks and applied-state checks.
