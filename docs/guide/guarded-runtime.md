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

An operator can configure `RUNTIME_GUARD_MANIFEST_FILE` as an absolute path to a
regular JSON file owned by root or the application user. The file must not be
writable by other users or groups. Use mode `0600`. The application reads it
again for every decision. A missing, disabled, malformed or changed declaration
stops the protected request.
A model or topology change stops access while declared and serving state differ.
Restoring identical declared and applied state can restore access. A different
definition or configuration needs operator re-enrollment and guard verification;
this first installation does not update enrollment automatically.

The declaration has exactly these fields:

| Field | Meaning |
| --- | --- |
| `version` | Integer `2`. Older declarations remain disabled. |
| `enabled` | Boolean `true` only after the installation has been verified. |
| `file_digest` | SHA-256 of the complete declared native file configuration. |
| `effective_digest` | SHA-256 of the complete declared effective configuration. |
| `applied_digest` | SHA-256 of the complete applied configuration, excluding only three per-request measurements. |
| `models` | At most 32 exact API-owned model IDs, each with the fields below. |

Each model has `fingerprint`, `key_choice`, `key_name` and `key_digest`.
The fingerprint includes the complete raw resource and its native revision.
`key_choice` is `none` or `shared`. For `none`, both key fields are empty strings.
For `shared`, the name is the existing managed `key-<32 lowercase hex>` basename;
the digest binds its exact file contents. No provider key value belongs in the
declaration. Configuration digests use UTF-8 JSON with sorted keys, no extra
spacing and no non-finite numbers.

Enrollment is trusted operator configuration. Model approval, developer input
and client headers cannot enroll a model. Only exact OpenAI, Anthropic and local
custom-completions definitions are supported here. Personal keys, file-owned
models, wildcard names and virtual or fallback aliases stay unavailable.
An enrolled raw model must have an explicit `id` equal to its API model ID.
Name-only models remain unavailable: their compiled backend names contain an
index that can change when unrelated models are added or removed.

Both callbacks also read the current applied configuration through an exact
operator-authenticated private route on port 4000. The read is limited to 1 MiB,
does not follow redirects and never uses developer credentials. It does not
expose the native admin listener to developers. The applied digest excludes only
`requestLatency`, `pendingRequests` and `totalRequests` inside the native AI
provider's endpoint measurement object. Health, eviction, capacity, provider
addresses, policies, creation times and unknown fields remain bound. Fields with
those measurement names elsewhere also remain bound.

Applied readback is a current snapshot, not a lock across inference. The pinned
gateway can read routing and selected-backend policy at different stages of a
request. Stable model IDs keep the file-owned final guard attached during normal
model updates; its constant definition fingerprint rejects a changed definition.
The installer must disable enrollment before changing those guard policies.
Arbitrary concurrent operator replacement of the guard file is outside this
fixed installation's supported boundary.

Shared keys use immutable filenames. Replace a key through model management,
which creates a new filename and resource revision, then enroll the new binding.
An in-place content change, missing file or symbolic link denies access. A file
read proves current content availability; it does not attest the credential
already loaded into a native serving process.

The installer disables enrollment throughout publication and verifies exact
compiled entry/final guards, private operator routes, stable model targets and
provider definitions before enabling. Desired management readback alone is
insufficient. If replacing the enabled manifest fails, it attempts to disable it;
if cleanup also fails, the access state is unconfirmed and the launcher stops the
gateway. Re-enrollment always starts a fresh gateway process.
Existing gateways, Kubernetes, replicas and release gateway selection remain
separate work.

Model setup also needs to test a provider before the model is approved. The
private `POST /internal/runtime/installed/operator-validation` callback preserves
that operator workflow. It requires both the current gateway runtime key as its
Bearer credential and the separate private callback key, plus the exact
`X-Keeplane-Installed-Runtime: operator` marker. Its body contains only `model_id`
and `definition_fingerprint`. Success returns `{"allowed": true}`; it does not
attest developer access, approval or enrollment. Developer credentials cannot
use it, and it never contacts a provider itself.

The native installation overwrites the marker on both listeners
before authorization: `operator` on private port 4000 and `1` on protected port
5000. Every selected model still calls authorization. Its native CEL expression
chooses the callback path and constant metadata for that listener; a missing
marker must fail. Client headers cannot select operator validation on port 5000.
The protected route accepts only `POST /v1/chat/completions`. Outbound headers
are replaced after final authorization and native provider authentication:
keyless models retain only Content-Type; shared models also retain their native
provider credential. Unknown Keeplane headers, cookies, developer credentials
and operator credentials never belong upstream. Native administrator tracing
can contain credentials; port 15000 stays on the gateway's loopback interface,
and only the exact authenticated applied-state route is proxied.
