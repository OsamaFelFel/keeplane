# Live gateway model replacement — 2026-10-09

Environment: protected Docker account preview at port 3001, agentgateway
1.6.0 and the fixed-answer local model fixture. The original preview and all
existing gateway resources kept running. The test created a unique gateway
resource and removed its own approval and resource afterward.

`python3 tests/e2e/test_model_replacement.py` followed the
[plain-English cases](../model-replacement-cases.md): **5 passed, 0 failed,
cleanup complete**. The [JSON report](2026-10-09-model-replacement.json)
records the HTTP observations. A model created directly in the gateway
appeared as outside and unapproved. After Keeplane approved it, the model
answered. Changing its upstream model ID under the same name advanced the
gateway resource revision to 2. Keeplane then showed it as unapproved and
returned HTTP 403, requiring setup again.

An expanded test found an approval rollback bug: returning the resource value
to its original definition at gateway revision 3 made Keeplane accept the old
approval and answer without reapproval. The
[before-fix report](2026-10-09-model-replacement-rollback-before.json) records
**4 passed, 1 failed**, with complete cleanup. Keeplane now includes the
gateway resource revision in its approval fingerprint. The final run kept the
model blocked after the rollback and allowed an answer only after reapproval.
If a managed gateway resource lacks a usable revision, Keeplane now refuses
approval; the isolated catalog check covers that fail-closed rule.
The Data classes API also omitted the changed model from the Public class,
refused a new class association to its stale approval, and listed the model
again after reapproval. The data-class, model-edit, model-approval, account
and original model-preview regressions passed 8/8, 5/5, 10/10, 13/13 and
7/7 after this change.
The earlier model edit, model approval, account, data-class and original model
preview suites passed 5/5, 10/10, 13/13, 8/8 and 7/7 after the fix. The
isolated catalog and data-class store checks passed too.

This proves the completed-update boundary for a new request. The approval
fingerprint is checked before forwarding, so a concurrent gateway update
between the check and the actual model call remains a release risk. A
gateway-side rule or equivalent atomic binding must close that race.
