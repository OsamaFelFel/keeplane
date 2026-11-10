# CLI provider-key command cases

`test_cli_provider_keys.py` uses an actual loopback HTTP fixture and synthetic
credentials. It does not run the Django issuer, real provider or gateway.

- KC-01 Set a key through hidden input, inspect URL-encoded model status and remove it.
  Send the key only in the PUT body; preserve cleanup metadata without saving the
  provider key locally or printing credentials.
- Changed accounts, revoked credentials and account outages stop before prompting
  or contacting the key endpoint.
- A 503 after an applied mutation, or an invalid 200 result, reports uncertainty.
  There is one write attempt; a later status call reconciles the stored state.
- KC-02 Hidden input cannot fall back to echo. An explicit pipe accepts one bounded
  ASCII key; oversized, injected-newline and non-ASCII values never reach the API.
  Pasting either saved Keeplane credential as a provider key is refused locally.
- KC-03 When the server refuses `keys set` because Keeplane uses the customer's
  gateway, the CLI exits 1 with "Keeplane can't use developers' own keys with this
  installation's gateway, so your key for MODEL wasn't saved. Ask your Keeplane
  admin which models you can use." Any other 403 keeps "The requested action is
  unavailable." The key is never printed.

Actual OAuth/Django/key-store composition and personal dispatch are separate
acceptance checks; no result from this fixture proves them.
