# Spec 004 outside-model approval — 2026-10-09

Environment: local Docker, agentgateway 1.6.0 and the fixed-answer model
fixture. The protected Keeplane preview at port 3001 used a persistent SQLite
catalog volume; the original model preview at port 3000 remained running.

`python3 tests/e2e/test_model_approval.py` followed the
[plain-English cases](../model-approval-cases.md): **10 passed, 0 failed,
approval removed after the run**. The [JSON report](2026-10-09-model-approval.json)
records each HTTP observation. The approval survived a restart of the account
app. Removing it left the model visible in the gateway and made Keeplane refuse
the next call. A dynamically registered model kept its approval and answered
after an app restart. `test_model_catalog.py` passed the endpoint-change invariant.
After this change, the account suite passed 13/13 and the original local-model
suite passed 7/7. Python syntax, JavaScript syntax and Git whitespace checks
also passed.

This is not complete Spec 004: shared/developer provider keys, class-aware
routing, cloud endpoints, and live gateway model
replacement are not yet covered. The port 3000 preview bypasses this trial's
approval gate.
