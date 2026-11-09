# Runtime settings: cloud models through API keys only

Spec 009 ST30 (D185, ADR 030) and the runtime part of ST31 (ADR 029). Journey:
DEV-03, feeding DEV-04. Stand-in runtime, no network; run
`python -m pytest tests/unit/test_cli_runtime_settings.py`. KEY-09, with the
real OpenCode V2 2.0.27 binary, is in
[`tests/e2e/cli-runtime-cases.md`](../e2e/cli-runtime-cases.md).

| Case | Expected result |
| --- | --- |
| KEY-01 Only the gateway | The settings `keeplane code` gives the runtime name one provider, `keeplane`, through the built-in OpenAI-compatible package, with the address of the turn's usage relay on `127.0.0.1` (which sends everything on to the gateway alone) and the grant from `KEEPLANE_RUNTIME_GRANT` only. A provider policy denies every provider but `keeplane`. With a signed-in account the only header is the project ID. |
| KEY-02 No provider sign-in | Every built-in provider plugin is off (`-opencode.provider.*`: ChatGPT, OpenAI, Copilot, GitLab and other sign-ins, local-runner discovery); web fetch and web search stay off; the only plugin package is Keeplane's instruction plugin, when instructions are chosen. No key names a sign-in, a key or a credential. |
| KEY-03 Usage on streamed answers | The gateway model asks for usage on streamed answers (`supportsUsageInStreaming`, sent as `stream_options.include_usage`). |
| KEY-04 Reviewed settings pass | The settings check accepts exactly what `keeplane code` writes, with or without the instruction plugin: exactly the reviewed keys, the relay's address as the only provider address, the model entry exactly its name and `{"supportsUsageInStreaming": true}` (plus, when the developer saved some, a body of the reviewed request settings: REQ-06 in [`cli-request-settings-cases.md`](cli-request-settings-cases.md)), `share` `"disabled"` and `snapshots` `false`. A relay address that isn't plain HTTP on `127.0.0.1` with a port (the gateway itself, `localhost`, another host) is refused. |
| KEY-05 Sign-in paths refused | Adding an OpenAI or Anthropic provider, pointing the gateway provider or model at another package or address (the gateway itself, skipping the relay, or another loopback port), adding an API key, a provider key variable, an auth block, an `Authorization` header, an access token, a subscription, turning a sign-in plugin (ChatGPT, OpenAI, Copilot, GitLab, or every plugin) back on, turning web tools on, adding a repo plugin, loosening or dropping the provider policy, adding an unreviewed key (MCP, `auth`, `enabled_providers`) or leaving a reviewed one out, turning sharing (`auto`, `manual`) or snapshots on, giving the model entry anything besides its name and the usage flag (`provider.package`, `api.url`, `options.baseURL`, a limit, an empty, false or extended `compatibility`, another name), or giving the instruction plugin more than its options is refused, and the runtime is not started. |
| KEY-06, KEY-07 Usage from a turn | Moved: the relay now reads each turn's usage from the gateway's answers. See USE-01, USE-02 and USE-05 in [`cli-usage-cases.md`](cli-usage-cases.md). |
| KEY-08 No subscription command | The CLI has no command to sign in with a personal subscription: `login` signs in to Keeplane only, with `--server`, `--profile`, `--timeout` and `--device`. |
