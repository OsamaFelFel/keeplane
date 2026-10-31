# Recording settings changes

These cases cover spec 006 ST21: when settings changes are recorded, every
admin change to a model or a data class leaves a record of who changed what,
and when. Complexity picks are not covered; their levels are not decided yet.

SC-01, SC-02, SC-03, SC-05 and SC-06 run in separate control-plane processes on
a fresh database, through the same stores the admin screens use. SC-04 and
SC-07 run in the test process.

| Case | Given | Expected result |
| --- | --- | --- |
| SC-01 After install | A fresh install; an admin makes every change listed in SC-02, then the break-glass admin signs in | All three optional switches are off. The only record is the break-glass sign-in. |
| SC-02 Every change | Settings changes are on. The admin turns classes on, sets up a model, changes its classes, replaces its shared key, moves it to personal keys, sets up a second model and approves its changed gateway definition, adds, renames, re-approves and removes a class, removes both models (one from the gateway), and turns classes off. Several requests are repeated unchanged | 14 records, one per real change, in order, each naming the admin, the model or class, what changed and a UTC time. Unchanged repeats add nothing. A second app process sees the same records. |
| SC-03 One kind only | The admin turns settings changes on and off again, then turns held-back requests on, and makes the SC-02 changes | Turning on one kind leaves the other two off. No settings record is written while only held-back requests are on. |
| SC-04 No secrets | Settings changes are on. The admin adds a cloud model with a shared provider key, replaces the key, changes its classes and removes it | Four records describe the setup, the key replacement with its class change, the class change and the removal. No record contains either key, a key file name, the admin password or the model check prompt. |
| SC-05 Refused change | Settings changes are on. The admin tries a duplicate or too-short class name, an unknown model or class, an invalid on/off value, an unknown class for a model, an unknown key option, an unverified model definition, and removing an unknown model | Every attempt is refused. Classes, model approvals and the record count are exactly as before. |
| SC-06 Record cannot be written | Settings changes are on and the record write fails | Turning classes off, adding, renaming, re-approving or removing a class, setting up or changing a model, replacing its shared key and removing it each report storage as unavailable. Nothing changes. |
| SC-07 Through the admin API | Settings changes are on. The signed-in admin turns classes on, adds, renames and removes a class, and turns classes off through the API | The Audit records API lists the five changes under the admin's username, without the password. |

Project class choices are covered in the [project cases](project-cases.md).

Run on SQLite:

```sh
.venv/bin/python -m pytest tests/integration/test_settings_change_records.py
```

To run SC-01, SC-02, SC-03, SC-05 and SC-06 on PostgreSQL as well, set the
`KEEPLANE_TEST_POSTGRES_*` variables described in the
[persistence cases](audit-persistence-cases.md). Without them the PostgreSQL
cases are skipped and reported as skipped.
