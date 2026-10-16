# Private Personal key transport

This adapter is internal plumbing. It does not install a public route or enable
Personal models on the protected gateway.

- Require the current private gateway credential; a user Bearer or browser cookie
  alone never receives a provider key. Rotating the private credential withdraws it.
- Accept only bounded token-exchange metadata: the developer credential, project,
  fixed model and full definition fingerprint. Reject duplicate and extra fields.
- Select the developer from the subject credential, recheck current account and
  project/model policy, then resolve only that owner's definition-bound private key.
- Return the selected key only to this trusted adapter, with no-store headers.
  Replacement takes effect on the next call; removal, logout and policy withdrawal
  deny without returning a key. Errors reveal no credentials or file paths.
- The existing public installed gate still denies Personal models. Native
  enrollment, cache-disabled transport and applied-configuration verification must
  be connected and tested separately before coding can use this adapter.
