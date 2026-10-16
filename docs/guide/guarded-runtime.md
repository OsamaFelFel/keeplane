# Guarded model access

The managed local preview can expose a guarded model endpoint on loopback port
5000. Start the normal preview and add an approved keyless or shared model in
Models first. Only newly registered models with a stable native ID can be
enrolled; existing name-only models are not rewritten.

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

Changing a model, key or gateway configuration can stop access. After making
changes through Models, rerun the opt-in command so a fresh gateway loads and
verifies the new state. Health changes also stop this fixed enrollment until
its declared and applied state match again.

This is an opt-in managed local trial. Personal keys, virtual/fallback models,
customer gateways, Kubernetes, replicas and a release image are outside its
current scope. The actual installer and isolated CLI journey have native
acceptance; a complete host launcher run remains unverified. See the
[operator contract](../architecture/runtime-authorization.md#managed-operator-contract)
for enrollment fields, private callbacks and applied-state checks.
