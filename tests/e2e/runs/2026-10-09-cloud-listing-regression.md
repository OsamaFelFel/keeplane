# Native cloud listing and local regression — 9 October 2026

The protected Docker preview now recognizes native OpenAI and Anthropic
gateway models as Cloud. It keeps models added outside Keeplane unapproved
until setup. The [plain-English cases](../cloud-listing-cases.md),
[live result](2026-10-09-cloud-listing.json), and
[verifier](../test_cloud_listing.py) are versioned with this change. The
OpenAI model used a local fixed-answer upstream and no provider key; this is
not evidence of a live cloud account.

The complete local regression passed **115/115 cases across 23 suites** after
correcting one test invocation. The [run manifest](2026-10-09-cloud-listing-regression.json)
records each suite command, environment override, exit status, duration, and
the correction. It includes Docker and kind model flows, Qwen, gateway
failover, supplied-gateway mode, account roles, data classes, model setup,
edit, replacement, Add model, Audit, runtime limits, and store invariants.

The first attempt to run `test_guarded_endpoint.py` on the host failed before
testing because its disposable `PREVIEW_PROVIDER_KEY` is set inside the Docker
app container. Running its documented command there passed all four cases.
No product behavior failed in the final run. Existing dated JSON reports
regenerated with random IDs and timestamps were restored to their committed
versions; the new cloud-listing result and this manifest preserve this run's
evidence.

After the regression, Docker `:3000/health` and kind `:13000/health` both
returned HTTP 200. The trial cloud resources and their temporary approval
were removed. The protected preview on port 3001 remains available through
its sign-in page.

This validates display and the no-key existing-gateway path. Shared provider
keys, developer-owned keys, real provider behavior, and a final release
gateway remain separate work.
