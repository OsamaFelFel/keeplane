# CLI session logout

- **CLI-LOG-01:** Send an empty Bearer-authenticated DELETE for the explicit
  current session; report success only after 204 and never print the credential.
- **CLI-LOG-02:** Refuse redirects, unexpected success statuses, unavailable
  sessions, access refusals and policy outages without claiming revocation.
- **CLI-LOG-03:** In the isolated combined Django contract check, logout makes
  the next catalog request fail and leaves another account's session valid.

Run `python -m pytest tests/unit/test_cli_server_connection.py`.
