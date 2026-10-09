# Spec 004 local model edit — 2026-10-09

Environment: protected Docker account preview at port 3001, agentgateway
1.6.0 and the fixed-answer `local-fixture` model. The fixture was unapproved
before the run. The original port 3000 preview kept running.

`python3 tests/e2e/test_model_edit.py` followed the
[plain-English cases](../model-edit-cases.md): **5 passed, 0 failed, trial
approval removed**. The [JSON report](2026-10-09-model-edit.json) records the
HTTP observations. Editing approval from Public to Internal succeeded after
the live model check. An unknown class and a write without the admin action
header were refused without changing the approval. Removing Keeplane's setup
left the model in the gateway and stopped the next call through Keeplane.

The protected page served the Edit and confirmation dialog markup. JavaScript
syntax and Git whitespace checks passed. The earlier model approval,
accounts, data-class and original model-preview regressions passed 10/10,
13/13, 8/8 and 7/7 respectively after this change. Their JSON reports in
this directory record the rerun. An authenticated interactive browser
walkthrough remains to be done. This trial covers no-key outside models only;
gateway removal for Keeplane-owned models and provider-key edits remain open.
