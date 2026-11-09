# Request settings per model

Spec 004 ST26 (ADR 030, task 009-12). Journey: none (Spec 004). Stand-in
runtime and stand-in gateway, no network; run
`python -m pytest tests/unit/test_cli_request_settings.py`. REQ-08, with the
real OpenCode V2 2.0.27 binary, is in
[`tests/e2e/cli-runtime-cases.md`](../e2e/cli-runtime-cases.md). The gateway's
own pass-through of these settings to the provider is PROTO-01 in
[`native-runtime-protocol-cases.md`](../integration/native-runtime-protocol-cases.md).

| Case | Expected result |
| --- | --- |
| REQ-01 Saved settings become the model's options | Temperature, top_p, max_tokens and reasoning_effort saved under `"models"` for the turn's model in the CLI settings file become that model's request body in the runtime's settings, with the same names, values and types, and the runtime settings check accepts them. Each works on its own. Another model's settings are not used. With none saved, or an empty object, the model entry has no body: Keeplane adds no setting of its own. |
| REQ-02 Unchanged through the relay | A request carrying those settings goes through the turn's usage relay, and the gateway receives the same body, byte for byte. |
| REQ-03 Routing settings refused | A provider (`provider`, `package`), address (`baseURL`, `api_base`), key (`apiKey`, `api_key`, `headers`, `env`) or plugin (`plugins`, `mcp`) setting is refused, naming the setting, its kind and the file, without printing its value. The runtime is not started. |
| REQ-04 Other settings refused | Any other setting (`seed`, `stop`, `top_k`, `frequency_penalty`, `maxOutputTokens`, a name with a stray space) is refused, naming the four allowed settings. |
| REQ-05 Values checked | `temperature` must be a number from 0 to 2, `top_p` from 0 to 1, `max_tokens` a whole number from 1 to 1,000,000 and `reasoning_effort` one of none, minimal, low, medium, high or xhigh. Text, true or false, NaN and out-of-range values are refused with the allowed values; values at the limits pass unchanged. |
| REQ-06 Runtime check stays strict | The runtime settings check accepts a model entry that adds only a body of the allowed settings with valid values, and refuses an empty or non-object body, an address, a key, an unreviewed setting, a bad value, or a body that would change the model, messages, streaming or usage request. |
| REQ-07 `keeplane code` | With a refused setting, `keeplane code` prints the message, exits 1 and starts no runtime. With valid settings the runtime gets them as the model's body. |
