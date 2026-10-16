# CLI OAuth account cases

Run `test_cli_oauth_identity.py` with the separate trial dependencies and
`-m optional`. Each case uses a disposable database and synthetic credentials.

- A bound, unexpired runtime credential resolves the current Keeplane account;
  access and refresh token columns contain no reusable token.
- Account role, activity, password, expiry and current account binding are checked
  again. Unbound tokens, unknown clients, incorrect grants/scopes and plaintext
  token records are refused. Turning acceptance off refuses the next request.
- OAuth credentials cannot serve as browser session cookies. Protected model
  listing and the private gateway callback still check the current project class
  and complete model definition. Project registration derives the current account.
- Explicit CLI logout revokes its own access/refresh pair while preserving another
  CLI credential and browser session. A cookie alone cannot revoke either.
- Global revocation removes account bindings, grants, approved device grants and
  native sessions atomically. Rollback preserves access. Account deletion still
  cascades with acceptance off and preserves another account's credential.
- Issuance refuses an account whose password changed after authorization. A
  database outage returns an unavailable response without exposing credentials.

These cases exercise account integration; browser PKCE, device protocol, actual
CLI sign-in and multi-replica checks follow in separate focused changes.
