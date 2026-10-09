# Audit in the local preview

Open the protected preview at `http://127.0.0.1:3000/audit` and sign in as an
admin. All three record kinds start off. Turn on **Changes to models, routing
and data classes**, then add or edit a data class, or set up a model already in
the gateway. The Records table shows the signed-in username, time and change.
Search and **Show** narrow the list; Previous and Next page through 25 rows.
Turning recording off stops new records. Older records remain visible.

The current settings producer covers Keeplane model setup/removal and data-class
add/edit/removal. Complexity-level picks and model registration are not yet
implemented as Keeplane settings flows. The held-back-request and model-answer
switches persist independently, but their event producers await detection and
developer-task flows. Do not use those switches as evidence that those flows
already produce records. Request text and provider credentials are never
written by the current settings producer.

This slice uses the protected preview's persistent SQLite volume. The same
transaction writes each data-class or model-approval change and its audit
record. Production storage, retention, redaction and shared-state deployment
remain to be designed and tested before a customer release.

The reusable [plain-English cases](../../tests/e2e/audit-cases.md) run with
`python3 tests/e2e/test_audit.py`; the isolated store check runs with
`python3 tests/e2e/test_audit_store.py`. The dated JSON run under
`tests/e2e/runs/` records the observed statuses. The live test leaves its
clearly named trial audit records in the local volume because audit records
are append-only; it removes temporary data classes and restores the switches.
