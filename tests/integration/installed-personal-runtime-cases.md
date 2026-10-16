# Managed Personal model access

- Enroll only an exact approved API model with a stable ID, a fixed HTTPS
  OpenAI/Anthropic definition and no global provider key. Installation does not
  read developer keys or change the raw model.
- Keep both current entry and selected-model checks. The installed-only private
  handoff checks enrollment again before resolving the current actor's own key.
- Use a replacement key on the next request. Deny a removed key, logged-out or
  disabled account, withdrawn class access, changed definition or changed wiring
  before reading a key or contacting the provider.
- Reject client-selected installed modes, missing callback identity, custom
  Personal providers, HTTP destinations and shared-key metadata.
- Keep existing keyless/shared operator validation unchanged. A Personal raw
  operator request cannot borrow a developer key. Virtual/fallback and customer
  gateways remain outside this managed installation.

The unit/HTTP cases use actual Django accounts, policy, binding metadata and
private key files with synthetic verified admission. Provider validation has
separate real HTTP cases. Native compiled-policy acceptance remains required.
The native serializer omits token-cache state; only the configured zero limit is
bound by file/effective digests. Fresh-process enrollment is required, and
already authorized requests are not cancelled by this check.
