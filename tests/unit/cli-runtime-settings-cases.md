# Runtime settings: cloud models through API keys only

Spec 009 ST30 (D185, ADR 030) and the runtime part of ST31 (ADR 029). Journey:
DEV-03, feeding DEV-04. Stand-in runtime, no network; run
`python -m pytest tests/unit/test_cli_runtime_settings.py`. KEY-09, with the
real OpenCode V2 2.0.27 binary, is in
[`tests/e2e/cli-runtime-cases.md`](../e2e/cli-runtime-cases.md).

| Case | Expected result |
| --- | --- |
| KEY-01 Only the gateway | The settings `keeplane code` gives the runtime name one provider, `keeplane`, through the built-in OpenAI-compatible package, with the gateway address and the grant from `KEEPLANE_RUNTIME_GRANT` only. A provider policy denies every provider but `keeplane`. With a signed-in account the only header is the project ID. |
| KEY-02 No provider sign-in | Every built-in provider plugin is off (`-opencode.provider.*`: ChatGPT, OpenAI, Copilot, GitLab and other sign-ins, local-runner discovery); web fetch and web search stay off; the only plugin package is Keeplane's instruction plugin, when instructions are chosen. No key names a sign-in, a key or a credential. |
| KEY-03 Usage on streamed answers | The gateway model asks for usage on streamed answers (`supportsUsageInStreaming`, sent as `stream_options.include_usage`). |
| KEY-04 Reviewed settings pass | The settings check accepts exactly what `keeplane code` writes, with or without the instruction plugin: exactly the reviewed keys, the model entry exactly its name and `{"supportsUsageInStreaming": true}`, `share` `"disabled"` and `snapshots` `false`. |
| KEY-05 Sign-in paths refused | Adding an OpenAI or Anthropic provider, pointing the gateway provider or model at another package or address, adding an API key, a provider key variable, an auth block, an `Authorization` header, an access token, a subscription, turning a sign-in plugin (ChatGPT, OpenAI, Copilot, GitLab, or every plugin) back on, turning web tools on, adding a repo plugin, loosening or dropping the provider policy, adding an unreviewed key (MCP, `auth`, `enabled_providers`) or leaving a reviewed one out, turning sharing (`auto`, `manual`) or snapshots on, giving the model entry anything besides its name and the usage flag (`provider.package`, `api.url`, `options.baseURL`, a limit, an empty, false or extended `compatibility`, another name), or giving the instruction plugin more than its options is refused, and the runtime is not started. |
| KEY-06 Usage from a turn | One request per step: a `step_start`, or answer events (text, reasoning, tool use) outside a printed step. Tokens come from the `step_finish` events: input is non-cached input plus cache reads and writes, output is visible output plus reasoning. A step whose answer had no usage, or whose `step_finish` the runtime didn't print, is a request without usage. OpenCode 2.0.27 prints only the text of a turn's last step. |
| KEY-07 No usage | A turn with no model request gives nothing to report; negative, fractional, boolean or text counts count as zero. |
| KEY-08 No subscription command | The CLI has no command to sign in with a personal subscription: `login` signs in to Keeplane only, with `--server`, `--profile`, `--timeout` and `--device`. |
