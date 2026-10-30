# Protected runtime model catalog

Run `python -m pytest tests/integration/test_runtime_catalog.py` against isolated Django storage.

- An active organization account can read a registered project's current eligible models without a previous usage record.
- Cookie-only requests and client identity, role or class claims do not authenticate.
- Missing or malformed bearer credentials, expiration, logout, disabled accounts and changed passwords return 401.
- Admin status does not bypass the stored project class. Changed gateway definitions disappear; classes off restores the set-up set.
- With no registered models (Spec 004 ST12), including models listed only by the gateway, the catalog returns 200 with an empty list whether classes are on or off, so the CLI can say no models are available yet.
- Unknown project contexts return 403. Database/gateway failure returns 503 rather than cached results.
- Credentials are not accepted on a non-loopback HTTP installation. Responses contain no credential and are not cached.
