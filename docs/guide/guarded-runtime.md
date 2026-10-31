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

After changing a model, shared key or gateway configuration, rerun the opt-in
command so a fresh gateway verifies the new state. Personal key changes apply
to the next request. Normal provider failures can recover on the next request;
endpoint eviction or wiring changes still require fresh enrollment.
After upgrading to the new health signature, rerun the launcher once to enroll
a fresh gateway. Existing manifests are not accepted automatically.

The protected route retries a model that is down twice before returning the
error, and never switches the model ([how it works](../architecture/runtime-authorization.md#a-model-that-is-down-or-too-small)).
This changes the generated route: an earlier installation keeps working without
the retry until you rerun the launcher once after upgrading.

This is an opt-in managed local trial. Virtual/fallback models,
customer gateways, Kubernetes, replicas and a release image are outside its
current scope. The installer, isolated CLI journey and host installation/restart
flow have native acceptance. The host check does not run the full preview
bootstrap in `up.py`. See the
[operator contract](../architecture/runtime-authorization.md#managed-operator-contract)
for enrollment fields, private callbacks and applied-state checks.
