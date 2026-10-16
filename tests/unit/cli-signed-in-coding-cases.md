# Signed-in coding cases

- A current profile account registers project use and reads the allowed model
  list before starting the runtime. The native configuration carries only the
  requested project header; its credential is absent from arguments and config.
- Changed account, withdrawn session, server outage or an unavailable model
  prevents runtime launch. Invalid gateway destinations stop before any request.
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
