# Guarded model access

The managed runtime installation is being added in small steps. The current
step provides private authorization callbacks; it does not expose a model
endpoint or make the signed-in coding command usable yet.

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

The installation must disable enrollment throughout publication and leave it
disabled on uncertainty. Before enabling, it must prove that the serving gateway
runs the expected entry and final-model guards. Desired management API readback
alone is insufficient. The next installation step will provide that workflow.
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

The planned native installation must overwrite the marker on both listeners
before authorization: `operator` on private port 4000 and `1` on protected port
5000. Every selected model still calls authorization. Its native CEL expression
chooses the callback path and constant metadata for that listener; a missing
marker must fail. Client headers cannot select operator validation on port 5000.
Compiled-policy and provider-contact checks are required before installation is
enabled. This HTTP prerequisite alone does not establish those native checks.
