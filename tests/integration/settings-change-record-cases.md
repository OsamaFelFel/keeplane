# Recording settings changes

These cases cover spec 006 ST21: when settings changes are recorded, every
admin change to a model or a data class leaves a record of who changed what,
and when. Complexity pick records are covered by SC-12 and SC-13 here and by
CL-INT-03, CL-INT-04 and CL-INT-10 in the
[complexity level cases](complexity-level-cases.md). Persona rule records are
covered by SC-14 and SC-15 here and by PR-INT-02, PR-INT-03 and PR-INT-10 in
the [persona rule cases](persona-rule-cases.md).

SC-01, SC-02, SC-03, SC-05, SC-06 and SC-11 to SC-15 run in separate control-plane
processes on a fresh database, through the same stores the admin screens use.
SC-04 and SC-07 to SC-10 run in the test process.

| Case | Given | Expected result |
| --- | --- | --- |
| SC-01 After install | A fresh install; an admin makes every change listed in SC-02, then the break-glass admin signs in | All three optional switches are off. The only record is the break-glass sign-in. |
| SC-02 Every change | Settings changes are on. The admin turns classes on, sets up a model, changes its classes, replaces its shared key, moves it to personal keys, sets up a second model and approves its changed gateway definition, adds, renames, re-approves and removes a class, removes both models (one from the gateway), and turns classes off. Several requests are repeated unchanged | 14 records, one per real change, in order, each naming the admin, the model or class, what changed and a UTC time. Unchanged repeats add nothing. A second app process sees the same records. |
| SC-03 One kind only | The admin turns settings changes on and off again, then held-back requests on and off again, then model answers on, and makes the SC-02 changes | Turning on any one kind leaves the other two off. No settings record is written while settings changes are off. |
| SC-04 No secrets | Settings changes are on. The admin adds a cloud model with a shared provider key, replaces the key, changes its classes and removes it | Four records describe the setup, the key replacement with its class change, the class change and the removal. No record contains either key, a key file name, the admin password or the model check prompt. |
| SC-05 Refused change | Settings changes are on. The admin tries a duplicate or too-short class name, an unknown model or class, an invalid on/off value, an unknown class for a model, an unknown key option, an unverified model definition, and removing an unknown model | Every attempt is refused. Classes, model approvals and the record count are exactly as before. |
| SC-06 Record cannot be written | Settings changes are on and the record write fails | Turning classes off, adding, renaming, re-approving or removing a class, setting up or changing a model, replacing its shared key and removing it each report storage as unavailable. Nothing changes. |
| SC-07 Through the admin API | Settings changes are on. The signed-in admin turns classes on, adds, renames and removes a class, and turns classes off through the API | The Audit records API lists the five changes under the admin's username, without the password. |
| SC-08 Key replacement fails | Settings changes are on. The admin replaces a model's shared key, the key is written to the gateway, but the model check fails once | The request reports that the previous key is still active. The gateway definition and approved classes are as before, and only the original setup record exists: putting the previous key back is not recorded as an admin change. |
| SC-09 Record write fails after the gateway step | Settings changes are on and the record write fails while the admin replaces a shared key, adds a local model, and adds a cloud model with a shared key | Each request reports that storage is unavailable. The previous key stays in the gateway, both new models are removed from the gateway, their key file is deleted, no approval is saved and no record is written. |
| SC-10 Change of owner | A model already in the gateway is approved, then set up by Keeplane, then approved again after its definition changed outside Keeplane | The records say "now set up by Keeplane" and "approved its changed gateway definition; no longer set up by Keeplane". |
| SC-11 Removal can't finish | Settings changes are on. The admin removes five Keeplane-added models from an in-memory gateway: one while the record write fails, one the gateway refuses to delete, one whose database commit fails after the gateway deleted it, one whose commit is kept but the connection drops before it is confirmed, and one with nothing failing. They also remove setup for a customer-added model, first while the record write fails | Each failed removal reports an error, and the model stays in the gateway with its approval bound to it; the one deleted before the commit failed is written back. The removal whose commit was kept is reported as done and not written back. The customer-added model is never sent for deletion. Only the three completed removals are recorded. |
| SC-12 Complexity picks | Settings changes are on and two models are set up. The admin changes Complex to one model, repeats it, moves it to the other, tries to remove that model, then goes back to Keeplane's pick twice | The removal is refused because Complex uses the model. Three records, one per real change, name the admin; a second app process sees them. |
| SC-13 Change and removal at the same time | Two app processes on one database. In one order, A removes a model and holds the settings lock at its gateway step while B chooses that model for Complex. In the other, A chooses the model for Complex and holds the lock after its record while B removes it | B waits for A's lock. Then the late level change is refused because the model is no longer set up, or the late removal is refused because Complex uses the model. Only A's change is stored and recorded. |

| SC-14 Persona rules | Settings changes are on and two models are set up. The admin adds an Architect rule, repeats it, moves it to the other model, tries to remove that model, then removes the rule twice | The removal is refused because the Architect rule uses the model. Three records, one per real change, name the admin; a second app process sees them. |
| SC-15 Rule and removal at the same time | Two app processes on one database. In one order, A removes a model and holds the settings lock at its gateway step while B adds an Architect rule for it. In the other, A adds the rule and holds the lock after its record while B removes the model | B waits for A's lock. Then the late rule is refused because the model is no longer set up, or the late removal is refused because the Architect rule uses the model. Only A's change is stored and recorded. |

Project class choices are covered in the [project cases](project-cases.md).

Run on SQLite:

```sh
.venv/bin/python -m pytest tests/integration/test_settings_change_records.py
```

To run SC-01, SC-02, SC-03, SC-05, SC-06 and SC-11 to SC-15 on PostgreSQL
as well, set the `KEEPLANE_TEST_POSTGRES_*` variables described in the
[persistence cases](audit-persistence-cases.md). Without them the PostgreSQL
cases are skipped and reported as skipped. The CI `postgres` job sets them
against a disposable PostgreSQL service and runs this file and the persistence
cases.
