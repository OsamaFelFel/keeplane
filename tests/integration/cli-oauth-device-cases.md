# CLI device fallback cases

Run `test_cli_oauth_device.py -m optional` with the pinned trial graph installed.
It exercises real Toolkit/Django requests and native accounts with synthetic
codes. No provider request or shared deployment is needed.

- Fixed device client/runtime initiation, existing-account code entry and explicit
  CSRF consent create a current password-bound approval. Cookie-only requests
  never authorize the token endpoint.
- Successful exchange creates hashed, account-bound access/refresh records and
  consumes the device approval atomically. Replay refuses. Device refresh and
  exact pair logout preserve the browser session.
- Pending polls enforce the persisted advertised interval; each early poll
  increases it by five seconds. Expired, denied, wrong-client, wrong-scope or
  withdrawn approvals produce no access token.
- Password change, global revoke, disabled owner and missing current binding are
  checked on the next actual exchange. Another account cannot steal a claimed
  code or confirm it; confirmation without code entry refuses.
- Approval and token-binding failures roll back status/token/consumption changes
  and retain a safe retry. Storage errors never return confidential error text.
- A deterministic pending-to-approved race defers rather than obtaining the
  newly found owner lock after the device row. The next request acquires owner
  first. This is a logic/order control, not proof of PostgreSQL lock scheduling.
- Separate direct-peer initiation and owner entry budgets use existing limits;
  forwarded IP headers cannot reset them. Colliding user codes refuse the new
  source while preserving the original.
- Trial-off, insecure origin, edited clients, duplicate fields, query/body
  ambiguity, excessive bodies and unsupported scope/client are refused.

Stock component failures and the comparison extension remain private. This PR
does not install optional packages or provide the CLI device polling command.
PostgreSQL concurrent issuance and real-browser/CLI fallback acceptance remain
explicit follow-ups.
