# Runtime session logout

Run `python -m pytest tests/integration/test_runtime_logout.py` with isolated Django storage.

- DELETE with the explicit bearer credential revokes only that session, returns 204 and prevents reuse.
- Another session in browser cookies remains valid. Cookie-only or invalid credentials cannot revoke it.
- A body containing account claims is rejected without revoking either session.
- Runtime headers do not bypass CSRF on sign-in, account changes or browser sign-out.
- A runtime marker without the exact header authenticator and authenticated permission keeps CSRF checks.
