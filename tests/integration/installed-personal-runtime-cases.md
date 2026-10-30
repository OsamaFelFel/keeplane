# Managed Personal model access

Entry checks the current owner's bound key before native backend selection;
missing → added can proceed without altering backend health. A known missing or
removed current key registration returns 403 with an instruction to add or replace
the key, so the coding runtime does not retry it as an outage. Unreadable key files,
database failures and unavailable policy still return 503. Selection returns
metadata only, and the final private handoff reads the current key again.
Before a turn, the CLI uses the [model choice](model-choice-cases.md) to move a
task to another allowed model when the key is missing; this entry refusal remains
for the requested model and for any request that reaches the gateway anyway.
Local initialization makes an existing provider-key volume private (0700),
preserving saved keys; the resolver continues to reject an exposed directory.

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
