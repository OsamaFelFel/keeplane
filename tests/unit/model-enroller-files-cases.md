# Model enroller files cases

Run `.venv/bin/python -m pytest tests/unit/test_model_enroller_files.py`
(tasks 004-01 and 002-02, ADR 027). The cases call
`components/control-plane/prepare_enroller_files.py`, the init step the Helm
chart runs in each gateway copy Pod before the model enroller, with temporary
folders, and load the app's settings in a fresh process. They need no
database, Kubernetes or Helm. The rendered chart is
[ME-01 to ME-10](../integration/chart-model-enroller-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| EF-01 | Prepare the files for each of three copies, by Pod name. | Each copy gets its own status role and password, and no other copy's status password appears in any of its files. |
| EF-02 | Prepare one copy's files. | Exactly seven files: the approvals password, database CA, both gateway keys, a signing secret, the status password and the status role. The folder is mode 0700 and each file mode 0400, owned by the running user. The guard folder is created, mode 0700 and empty. |
| EF-03 | Prepare twice. | Each signing secret is new and at least 48 characters: the enroller never gets the app's shared one. |
| EF-04 | Prepare again with a changed status password, as a restarted init step would. | The files are replaced with the new value and no temporary file is left. |
| EF-05 | Use a Pod name past the last copy, with a leading zero, empty, of another workload or with extra text. | Refused as "not one of the gateway copies"; nothing is written. |
| EF-06 | Leave out or spoil each setting: empty, upper-case, unsafe or repeated status roles; a missing or blank status or approvals password; the approvals password equal to this copy's status password; a short or malformed gateway key; a CA that isn't PEM or is missing. Then make the guard path a symbolic link. | Each is refused with a message naming the setting, never its value, and nothing is written. The symbolic link is refused as "not a private folder". |
| EF-07 | Load the settings with the status role from a file, then as a setting; then with an empty file, both forms at once, or a missing file. | The status connection uses the role from the file (or the setting), its password file and read-only transactions by default. An empty file, both forms, or a missing file stops start-up. |
