# Spec 005 starter data classes — 2026-10-09

Environment: the protected Docker account preview at port 3001, agentgateway
1.6.0 and the fixed-answer `local-fixture` model. Classes and approvals used
the persistent local SQLite volume. The original port 3000 preview kept
running.

`python3 tests/e2e/test_data_classes.py` followed the
[plain-English cases](../data-classes-cases.md): **8 passed, 0 failed, trial
resources removed**. The [JSON report](2026-10-09-data-classes.json) records
the observed HTTP results. The run covered starter classes, adding a class
with an approved model, duplicate and unknown-model rejection, renaming,
restart persistence, removal and admin action protection.

`python3 tests/e2e/test_data_classes_store.py` passed against an isolated
SQLite database. It checked that a project using a class blocks removal,
renaming keeps the model relationship, removing a model's last approved class
deactivates its approval, and the final data class cannot be removed. The
project-in-use case is a store test because the Projects workflow has not been
built yet.

After the data-class changes, the earlier live regressions passed: model
approval 10/10, accounts 13/13, original model preview 7/7. The model and
account JSON reports in this directory record the rerun. Python compilation,
JavaScript syntax and Git whitespace checks passed. A static browser check of
the Data classes and Add class layouts found the form controls consistent
with the supplied canvas; an authenticated interactive UI walkthrough is still
needed.

This trial does not yet provide project class assignment, class-aware routing
or personal-data detection. The direct port 3000 preview bypasses account and
class controls.
