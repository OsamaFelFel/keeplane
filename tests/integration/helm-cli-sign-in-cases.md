# Helm CLI sign-in

- Ordinary renders keep sign-in off and retain the existing migration command.
- Enabled PostgreSQL renders share one immutable image and HTTPS origin between
  serving copies and the migration Job; migrate, browser registration and device
  registration run in order with the separate migration credential.
- Supplied and managed gateway modes retain the same account-only behavior.
  No protected listener or internal authorizer is installed by this setting.
- External migrations remain supported; the operator must prepare the schema
  and both fixed clients. Missing, drifted or unreadable clients keep readiness
  at 503 without writes or row locks; disabled sign-in skips optional models.
- Registration refuses drift rather than overwriting it. Authorization keeps
  its existing transactional locking check.
- Invalid types, non-PostgreSQL settings and insecure origins refuse rendering.

Run `pytest tests/integration/test_cli_sign_in_chart.py tests/integration/test_readiness.py`.
With the optional pinned Toolkit graph, also run
`pytest -m live tests/integration/test_cli_sign_in_readiness.py`.
These checks do not replace the installed two-copy PostgreSQL/HTTPS journey.
