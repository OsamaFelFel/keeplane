# Signed-in coding cases

- A current profile account registers project use and reads the allowed model
  list before starting the runtime. The native configuration carries only the
  requested project header; its credential is absent from arguments and config.
- After the catalog check the CLI asks the server for a model choice. When the
  requested model needs the developer's own key and it is missing, refused or
  outdated, the runtime starts with the other allowed model and stderr says why
  and how to add the key. No other model, a choice outside the catalog, a
  malformed choice, or a 403/503 stops before launch; an older server without
  the route (404) keeps the requested model. See the
  [model choice cases](../integration/model-choice-cases.md).
- Spec 005 ST19: when the server reports the requested model `unavailable`
  (approved but not usable right now), the CLI says “… can't be used right now,
  so nothing was sent” and starts no runtime. An `unavailable` reason that still
  names a model is treated as an invalid choice.
- Repository settings (ST19 “The repo can't change it”): an `opencode.json` in
  the repository or its `.opencode/` folder, and `OPENCODE_CONFIG`,
  `OPENCODE_CONFIG_CONTENT` or `OPENCODE_MODEL` in the environment, all naming
  another model and provider, change nothing: the runtime gets only the chosen
  Keeplane model and the gateway URL. The gateway still refuses a model outside
  the class ([MC-20](../integration/model-choice-cases.md)).
- Changed account, withdrawn session, server outage or an unavailable model
  prevents runtime launch. Invalid gateway destinations stop before any request.
- No models yet (Spec 004 ST12): when the project's allowed model list is empty,
  the CLI says “No models are available for this project yet, so nothing was
  sent” and asks the developer to have an admin add or approve one. It asks for
  no model choice and starts no runtime. A model missing from a non-empty list
  keeps “This model is not currently allowed for the project.”
- Request settings (ST26): Keeplane's generated runtime configuration holds only
  the provider package, gateway URL, project header and model name, so it adds or
  replaces no request setting such as temperature. The gateway side is covered by
  the [native protocol cases](../integration/native-runtime-protocol-cases.md).
- Model down after the gateway's retries (Spec 004 ST16): when the runtime's
  error event carries a 429 or 5xx, `code` keeps its failing exit status, still
  prints the runtime's error, and adds “coder is unavailable right now, so this
  task stopped. Wait and try again, or run it with another model allowed for
  this project using --model: …” with the server's list. The runtime is started
  once, with the requested model only. Run
  `python -m pytest tests/unit/test_cli_model_outage.py`.
- No alternative left: the message ends with the existing no-models message.
- Task too big for the model's context: “This task is too big for coder's
  context, so it stopped. Run it with another model allowed for this project
  using --model: …”, or the no-models message.
- An older server (404), an unavailable server (503) or a malformed list: the
  reason still shows and points to `keeplane models`; no list is printed.
- A 400, 401 or 403 error, an error without a status, or a successful turn asks
  for no alternatives and prints nothing extra.
- Private history records the issuer, account and project without credentials.
  Fresh credentials for the same account work; another account or project cannot
  reuse that history. Legacy unbound history is also refused.
- Timeout, termination and cancellation keep their exit statuses and cannot
  print credentials from exception output. Server and runtime errors are redacted.

These HTTP and process-boundary checks use a synthetic account server and a
controlled runtime process. Actual Django sign-in, native tool execution and
protected-gateway withdrawal require the separate integration cases.

The optional [native case](../e2e/test_cli_signed_in_coding_native.py) runs two
actual V2 processes through the shared `code` command. It checks read/edit tools,
the project header, retained tool history, fresh credentials for the same account,
another-account refusal and withdrawal before another launch. Its account server
is synthetic; it does not prove Django issuance or native gateway enforcement.
