# Guarded model access

The managed local preview can expose a guarded model endpoint on loopback port
5000. Start the normal preview and add an approved model in Models first:
keyless/shared models and Personal OpenAI/Anthropic models are supported.
Only newly registered models with a stable native ID can be enrolled; existing
name-only models are not rewritten. Developers
[add their own key](cli-provider-key-commands.md) before using a Personal model;
keys remain on the server.

For browser CLI sign-in, supply an explicitly prepared OAuth-capable trial app
image and the current first-party CLI. The default preview image does not include
that optional dependency set. This command neither installs those dependencies
nor selects a release image:

```sh
python3 deploy/local/up.py --runtime-model MODEL_ID --runtime-app-image YOUR_TRIAL_IMAGE
```

Repeat `--runtime-model ID` to enroll more models. Use `--runtime-port 5001` to
change the host port. The resulting coding endpoint is
`http://127.0.0.1:5000/v1` (or the chosen port); pass it as the coding command's
`--gateway`. Sign in through [the CLI browser flow](cli-browser-login.md). Provider
keys remain on the server. The caller supplies its current credential and
registered `X-Keeplane-Project-ID`; the project header is not proof of repository
or content identity.

The launcher stops the old managed gateway before preparing disabled enrollment,
starts a new process, migrates the selected app image and verifies the compiled
guards before enabling access. A failed enrollment stops that managed gateway.
Fix the reported setup problem, then rerun the same opt-in command. Existing
accounts, API models and keys remain stored. Do not edit the generated manifest
to make a failed check pass. Ordinary startup without runtime flags is unchanged.

After enrollment the launcher starts the private model enroller
(`model-enroller`). It keeps the protected checks in step with the models saved
in Models and routing, without restarting the gateway or the app:

- A model you add is enrolled within a few seconds.
- A developer's own provider key needs no enrollment: a new or replaced one
  applies to their next request. A shared key is different (see the next
  point).
- A model you remove is refused as soon as you remove it.
- A model you edit (or a shared key you replace) is refused at once. Its new
  setup is enrolled after about 3 minutes and 16 seconds, once every request
  that started under the old setup has finished its retries. While a change
  waits, every protected model can be refused if the gateway's own state moved;
  the enroller's log says "A model change is waiting".

The enroller has no port, reads models through a read-only database connection
and is the only service that writes the private installation volume after
enrollment; the app's copy of that volume stays read-only. Of the app's account
volume it mounts only the `database` folder, read-only, so it can't read the
signing secret or anything else kept there. Earlier previews kept the database
at `/state/keeplane.sqlite3`. Before the first release Keeplane doesn't carry
trial data forward, so this preview starts a fresh database in the folder and
leaves the earlier file unused and unchanged; start-up prints a notice when it
finds one. To reset the preview fully, run `docker compose down`, then
`docker volume rm keeplane-accounts-trial_model-approvals`, and start it again. Check it with
`docker compose -f compose.yaml -f deploy/local/runtime.yaml logs model-enroller`.
If it reports that enrollment did not complete, protected access stays refused
and it tries again every 2 seconds. To stop automatic changes, stop the
`model-enroller` service. Access then stays as last enrolled until a model
changes; after that, protected models are refused until you start it again or
rerun the launcher.

Changing the gateway configuration itself still needs the opt-in command again
so a fresh gateway verifies it. Personal key changes apply to the next request.
Normal provider failures can recover on the next request; endpoint eviction or
wiring changes still require fresh enrollment.
After upgrading to the new health signature, rerun the launcher once to enroll
a fresh gateway. Existing manifests are not accepted automatically.

The protected route retries a model that is down twice before returning the
error, and never switches the model ([how it works](../architecture/runtime-authorization.md#a-model-that-is-down-or-too-small)).
This changes the generated route: an earlier installation keeps working without
the retry until you rerun the launcher once after upgrading.

This is an opt-in managed local trial. Virtual/fallback models,
customer gateways, Kubernetes, replicas and a release image are outside its
current scope. The enroller has been checked only against a simulated gateway;
it has not yet been run against the real gateway image. The installer, isolated CLI journey and host installation/restart
flow have native acceptance. The host check does not run the full preview
bootstrap in `up.py`. See the
[operator contract](../architecture/runtime-authorization.md#managed-operator-contract)
for enrollment fields, private callbacks and applied-state checks.
