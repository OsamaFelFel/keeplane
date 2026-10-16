# Guarded model access

The managed runtime installation is being added in small steps. The current
step provides private authorization callbacks; it does not expose a model
endpoint or make the signed-in coding command usable yet.

An operator can configure `RUNTIME_GUARD_MANIFEST_FILE` as an absolute path to a
regular JSON file owned by root or the application user. The file must not be
writable by other users or groups. Use mode `0600`. The application reads it
again for every decision. A missing, disabled, malformed or changed declaration
stops the protected request.

The declaration has exactly these fields:

| Field | Meaning |
| --- | --- |
| `version` | Integer `1`. |
| `enabled` | Boolean `true` only after the installation has been verified. |
| `file_digest` | SHA-256 of the complete declared native file configuration. |
| `effective_digest` | SHA-256 of the complete declared effective configuration. |
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
