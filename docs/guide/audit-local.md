# Audit in the local preview

Open the protected preview at [Audit](http://127.0.0.1:3000/app/audit) and sign in as an
admin. Break-glass admin sign-ins are always recorded, with no off switch.
The other three record kinds start off. Turn on **Changes to models, routing
and data classes**, then add or edit a data class, or set up a model already in
the gateway. The Records table shows the signed-in username, time and change.
Search and **Show** narrow the list; Previous and Next page through 25 rows.
Turning recording off stops new records. Older records remain visible.

### Which changes are recorded

While **Changes to models, routing and data classes** is on, every admin change
to a model or a data class adds one record. Each record shows who made the
change, when, and a short description such as these:

| Admin change | Example description |
| --- | --- |
| Add or set up a model | `Set up model alpha; provider key: shared; approved classes: Public` |
| Change a model's key option or approved classes | `Changed model alpha: provider key: shared to personal` |
| Replace a model's shared provider key | `Changed model alpha: replaced the shared provider key` |
| Approve a model again after its gateway definition changed | `Changed model beta: approved its changed gateway definition` |
| Remove Keeplane's setup, or the model from the gateway | `Removed Keeplane setup for model alpha`, `Removed model beta from the gateway` |
| Change a complexity pick, or go back to Keeplane's pick | `Changed complexity pick Complex: Keeplane's pick to model alpha`, `Changed complexity pick Complex: model alpha to Keeplane's pick` |
| Turn data classes on or off | `Turned data classes on; added starter classes: Public, Internal, Confidential` |
| Add a data class | `Added data class Finance; approved models: alpha` |
| Rename a class or change its approved models | `Changed data class Finance: renamed to Finance team; approved models: alpha to none` |
| Remove a data class | `Removed data class Finance team; it was approved for models: alpha, beta` |
| Choose a project's data class | `Changed data class for project Example (…) from none to Public` |

A request that changes nothing, or that Keeplane refuses or rolls back, adds
no record. For example, when a replacement shared key fails its check and
Keeplane puts the previous key back, nothing is recorded. A
record never contains a provider key, key file, password, session token or
prompt text. Keeplane's own complexity picks moving after a model is added or
removed are not admin changes and add no record.

### Which model requests are recorded

While **Which model answered each task** is on, Keeplane adds one record each
time it lets a developer's request through to a model: the last check before
the gateway sends the request on. Choose **Model answers** under **Show** to
list only these. Each record shows the developer's username, the time, and the
model and project, for example
`Request sent to model gpt-4.1; project payments-api`. Search finds the
developer, model or project.

A record means the request was sent, not that the model answered it: a
provider error after the check is still recorded. One coding task usually
makes several records, because the CLI asks the model several times per task
(reading files, running tools), and each retry of a model that is down is
checked and recorded again. A request Keeplane refuses (signed out, a project
or model the developer may not use, a model that is not installed) adds no
record. The record never contains the prompt, the answer, a session token, the
gateway credential or a provider key. If the record cannot be written, the
request still goes ahead and the app logs a warning,
`Model answers record was not written; the request was allowed`, with only the
error kind. Records are written only on a managed guarded runtime
([guarded runtime](guarded-runtime.md)); the experimental shared check at
`/internal/runtime/authorize` does not write them.

The held-back-request switch persists independently, but its records wait for
detection. Do not use that switch as evidence that held-back requests are
recorded yet.

Records are stored in the application database: the preview's SQLite volume, or
PostgreSQL when configured. The same transaction writes each data-class or
model-approval change and its audit record: if the record cannot be written,
the change is not saved and the screen reports that storage is unavailable. A break-glass session and its
mandatory record commit together; if the record cannot be written, the sign-in
fails. The record contains the account and time, not the password or session
token. Every app copy finds the same records, and they survive restarts and
upgrades. Nothing deletes them automatically. See
[Audit storage](../architecture/audit-storage.md). Redaction for held-back
requests remains to be designed before that producer is connected.

The reusable [plain-English cases](../../tests/e2e/audit-cases.md) run with
`.venv/bin/python -m pytest tests/e2e/test_audit.py -m live`; the isolated store check runs with
`.venv/bin/python -m pytest tests/integration/test_audit_store.py`. The
[settings-change cases](../../tests/integration/settings-change-record-cases.md)
check each change above on SQLite and, when configured, PostgreSQL. The
[model-answer cases](../../tests/integration/model-answer-record-cases.md)
check model request records the same way. The [mandatory sign-in cases](../../tests/e2e/audit-cases.md#always-on-break-glass-sign-ins)
run in both an isolated store and the Docker preview. The dated JSON run under
`test-results/` records the observed statuses. The live test leaves its
clearly named trial audit records in the local volume because audit records
are append-only; it removes temporary data classes and restores the switches.
The Audit screen now uses the same React shell and shadcn components as Users
and Data Classes. Its [browser cases](../../tests/browser/audit-cases.md) cover
the checked, disabled break-glass control, independent switches, search, Show,
paging and the 320px layout. The earlier Audit HTML page is no longer served.
