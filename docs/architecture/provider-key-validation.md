# Check a developer's provider key

The internal `DjangoProviderKeyValidator(gateway)` accepts a trusted owner ID,
model ID and submitted key. It checks the current Keeplane-approved `personal`
model definition, sends one fixed provider request, then checks the definition
again. Success returns `VerifiedProviderKey` with those IDs and the definition
fingerprint. This result is internal metadata, not an authentication credential.
The [internal key store](developer-key-storage.md) consumes this verification.
No public route, CLI command or task dispatch is connected here.

Supported definitions are the existing `openAI` and `anthropic` cloud formats,
with only `model` and optional `baseUrl` parameters and no configured provider
authentication. HTTPS is required; an explicit constructor flag permits HTTP
only for loopback synthetic fixtures. Unknown formats fail before key contact.
This transport accepts non-space ASCII provider keys only.

The request contains only “Reply OK.” and a one-token generation limit, using
[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
or [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create).
It uses no redirect, retry or proxy. A private stdin pipe supplies the key to an
owned worker; output is discarded and the response is capped at 64 KiB. The
default eight-second provider-exchange deadline kills and reaps that worker;
the configurable limit cannot exceed ten seconds. It includes DNS and response
reading. Parent process hard termination is outside this cleanup guarantee.

Management reads send no provider key and use single five-second socket timeouts,
without retries; those reads do not have a total wall deadline. Unsupported or
unavailable responses issue no verification; provider 401/403 means refused.
Success proves this check, not future key acceptance or inference readiness.

`require_current(verification)` runs inside a storage transaction, locks current
approval and checks its fresh registry fingerprint. The internal store persists
that binding and rechecks it before mutation; final dispatch must check the actual
selected definition too. Account-removal cleanup and public admission remain
separate prerequisites. Run the [synthetic HTTP cases](../../tests/integration/test_provider_key_validation.py)
with `python -m pytest tests/integration/test_provider_key_validation.py`.
