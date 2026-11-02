# Model enroller files cases

Run `.venv/bin/python -m pytest tests/unit/test_model_enroller_files.py`
(tasks 004-01 and 002-02, ADR 027). The cases call
`components/control-plane/prepare_enroller_files.py`, the init step the Helm
chart runs in each gateway copy Pod before the gateway and the model enroller
start (it also installs Keeplane's protected runtime there), with temporary
folders, and load the app's settings in a fresh process. They need no
database, Kubernetes or Helm. The rendered chart is
[ME-01 to ME-15](../integration/chart-model-enroller-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| EF-01 | Prepare the files for each of three copies, by Pod name. | Each copy gets its own status role and password, and no other copy's status password appears in any of its files. |
| EF-02 | Prepare one copy's files. | Exactly seven files: the approvals password, database CA, both gateway keys, a signing secret, the status password and the status role. The folder is mode 0700 and each file mode 0400, owned by the running user. The guard folder is created, mode 0700 and empty. |
| EF-03 | Prepare twice. | Each signing secret is new and at least 48 characters: the enroller never gets the app's shared one. |
| EF-04 | Prepare again with a changed status password, as a restarted init step would. | The files are replaced with the new value and no temporary file is left. |
| EF-05 | Use a Pod name past the last copy, with a leading zero, empty, of another workload or with extra text. | Refused as "not one of the gateway copies"; nothing is written. |
| EF-06 | Leave out or spoil each setting: empty, upper-case, unsafe or repeated status roles; a missing or blank status or approvals password; the approvals password equal to this copy's status password; a short or malformed gateway key; a CA that isn't PEM or is missing. Then make the guard path a symbolic link. | Each is refused with a message naming the setting, never its value, and nothing is written. The symbolic link is refused as "not a private folder". |
| EF-07 | Load the settings with the status role from a file, then as a setting; then with an empty file, both forms at once, or a missing file. | The status connection uses the role from the file (or the setting), its password file and read-only transactions by default. An empty file, both forms, or a missing file stops start-up. |
| EF-08 | Prepare a copy with its callback key, both key hashes and the chart's gateway configuration. | The guard holds exactly a disabled declaration (`version` 2, `enabled` false), the callback key, and `trusted.json` and `gateway.json`, byte for byte the same and in the installer's canonical JSON, with both hashes written out and the gateway database address left with its variable. The guard is mode 0700, each file mode 0600 and owned by the running user; the enroller's seven files are as in EF-02. |
| EF-09 | Prepare again after the enroller had enabled a declaration, recorded served models, left a candidate and written a guarded configuration, with a new callback key. | The declaration is disabled again, the served-models record and the candidate are gone, `gateway.json` is the trusted base again and the callback key is the new one. The enroller's lock stays and no temporary file is left. |
| EF-10 | Prepare a configuration whose key policies also name the next hashes, with and without them. | With them, each policy lists the current hash then the next one; without them the step is refused as "names a key hash this copy was not given". |
| EF-11 | Leave out or spoil each runtime setting: no, short or malformed callback key; a missing or malformed hash; no, malformed or non-object configuration; a non-loopback admin address; a next key hash the step wasn't given; or one of the enroller's own settings. | Each is refused with a message naming the setting, never a key, and nothing is written: neither the enroller's files nor the guard. |
| EF-12 | Prepare a configuration of exactly 122880 bytes (120 KiB), then one byte more, then one under the limit in characters but over it in bytes. | The first is prepared. The others are refused as "is over 122880 bytes (120 KiB)", the most the chart passes as one environment value, and nothing is written. |
| EF-13 | Prepare a configuration whose gateway database URL reads its password from `${GATEWAY_DB_PASSWORD}` and that names another `${GATEWAY_…}` variable; then leave out each key hash the configuration names. | The first is prepared, with both variables left as they are for the gateway to read and the key hashes written out. Leaving out a key hash the configuration names is still refused: a current hash as "is missing", a next hash as "names a key hash this copy was not given". |
