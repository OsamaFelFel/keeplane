# Per-copy guard status

**Edition:** Open Source. These cases cover Spec 004 ST10 and ST23–ST25 and
Spec 002 ST1, ST4 and ST5 under ADR 027 ("Kubernetes", "What the app checks"),
tasks 004-01 and 002-02. In Kubernetes the app can't read a gateway copy's
private guard, so each copy's model enroller records the guard it confirmed in
the guard-status table, one row per copy (named by its StatefulSet Pod name).
The app allows a protected check only when the copy that sent it has a
confirmed row listing the model with the same fingerprint, and that copy's
gateway still matches it.

- [`test_guard_status_names.py`](../unit/test_guard_status_names.py) (unit):
  GS-U01 to GS-U06.
- [`test_guard_status.py`](test_guard_status.py): GS-01 to GS-26, on SQLite,
  with the fake gateway of `test_model_enroller.py` and the HTTP checks of
  `test_installed_runtime.py`.
- [`test_guard_status_postgres.py`](test_guard_status_postgres.py): GS-PG-01
  to GS-PG-14, on a disposable PostgreSQL server named by
  `KEEPLANE_TEST_POSTGRES_*` (CI's PostgreSQL job); skipped without one:

```sh
KEEPLANE_TEST_POSTGRES_HOST=127.0.0.1 KEEPLANE_TEST_POSTGRES_PORT=5432 \
KEEPLANE_TEST_POSTGRES_USER=keeplane KEEPLANE_TEST_POSTGRES_PASSWORD_FILE=/private/path \
python -m pytest tests/integration/test_guard_status_postgres.py -k postgresql
```

The server's user must be able to create roles and databases; each run
creates its own and drops them afterwards.

None of these runs a Kubernetes cluster or the real gateway image; the enroller
container, Helm values and a live run are separate work.

## Unit

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| GS-U01 Every check names the copy | Build a copy's guard for a keyless and a Personal model, naming `keeplane-gateway-1` | The entry check, each final check (its protected branch) and the Personal key exchange send `gateway_copy` = `keeplane-gateway-1`; operator validation names no copy. |
| GS-U02 Docker preview unchanged | Build the guard without a copy name | No check names a copy; the guard is byte-for-byte what it was before. |
| GS-U03 Only Pod names | Name the copy with an empty, upper-case, dotted, quoted, spaced, over-long or non-text name | Refused before any guard is built. |
| GS-U04 Which copy a guard names | Read the names back from a copy's guard, a preview guard, a guard mixing two copies and a malformed one | `{copy}`, `{none}`, both names, and unreadable. |
| GS-U05 Only the named copy's address | Look up `keeplane-gateway-1` and `-10` among three listed copies; then a prefix, an unlisted copy, wrong case, a name listed twice and an unusable list | The exact Pod's address each time; every other case is refused. |
| GS-U06 Policy read back | Read the (copy, role) pairs from the own-copy policy as PostgreSQL prints it, with and without the column cast; then a policy whose writes allow fewer pairs than its reads, with an added `OR true`, with `true` only, for a role it doesn't pair, for SELECT only, pairing a role or a copy twice; an app read policy for another role too, or for writes; an extra policy; no policies; the app read policy for another app role | The pairs the command wrote; every changed setup reads as "changed". |

## Enroller (SQLite)

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| GS-01 Confirmed with its models and time | The copy's enroller enrols a saved model | The copy's row is confirmed, holds the enabled declaration with the model's fingerprint and a confirmation time; it was cleared before the guard moved and confirmed after. |
| GS-02 Nothing changed | Run another pass | No write. |
| GS-03 After the operator's enrolment | Delete the row (as after the installer's first enrolment) and run a pass | The unchanged guard is recorded once. |
| GS-04 Nothing confirmed while the guard moves | Add a model; look at the row during the readback | It says nothing is confirmed; afterwards it lists both models. |
| GS-05 Never read back | The gateway never loads the new guard | The pass fails; the row says nothing is confirmed, with no declaration or time. |
| GS-06 Failed pass that changed nothing | After an enrolment, a pass fails because the gateway can't be read | The guard files and the row are unchanged: the last confirmation stands (ADR 027 "Failure"; associate product owner decision on #207). |
| GS-07 Row can't be written | The status write fails before a change | The pass fails and the guard files are untouched; the next pass, with the database back, enrols. |
| GS-08 Held change | A served model's destination changes | During the hold the row keeps the old confirmation; after it, the row has the new fingerprint. |
| GS-09 Everything withdrawn | The only model is removed | After the hold the row says nothing is confirmed. |
| GS-10 The guard names this copy | A guard enrolled without a copy name meets the copy's enroller | It is re-enrolled naming the copy, then left unchanged. |
| GS-11 Docker preview | The preview enroller enrols | No row is written and no check names a copy. |
| GS-12 One copy never records for another | Build a copy's enroller with no recorder or another copy's | Refused. |
| GS-13 Setup checks | Set the copy name without the status database, or the reverse, or an invalid Pod name, or SQLite; then PostgreSQL without a read-only approvals connection, or with the same role for both | Refused at start. With neither set (the preview) nothing is needed; with PostgreSQL, a read-only approvals role and a separate status role, the recorder is ready. |
| GS-24 What is recorded | Record an incomplete declaration; name a copy that isn't a Pod name | Refused; nothing is written. |

## App per-copy check (SQLite, over HTTP)

The per-copy check is on, the copy list names `keeplane-gateway-0` and `-1`,
and the app has no declaration file.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| GS-14 Confirmed copy | Send the entry and final checks from `keeplane-gateway-0`, whose row lists the model | Allowed; every gateway read and the applied state come from that copy's address. |
| GS-15 No confirmed row | No row, an unconfirmed row, a malformed declaration, or only the other copy's row | 503 "Gateway authorization is unavailable", before any gateway read. |
| GS-16 Model not confirmed | Ask for a model the row doesn't list | 403. |
| GS-17 Stale row | The admin moves the model on while the row lists the old fingerprint | Both old and new fingerprints are refused until the copy confirms the new guard; then only the new one is allowed. |
| GS-18 Row no longer matches its copy | The copy's applied state or file changed, or the copy can't be read | 503. |
| GS-19 Unknown copy | The check names no copy, an invalid name, or a copy not in the list (even with a confirmed row); or the copy list is unusable | 400 for a missing or invalid name, 503 otherwise; nothing is read from any gateway. |
| GS-20 Status table unreadable | The row can't be read | 503. |
| GS-21 Check off | With the per-copy check off, send a check that names a copy | 400: the fields are exact, as before. Without a name the file is used and no row exists. |
| GS-22 Personal key exchange | Exchange a Personal key without a copy, from an unconfirmed copy, then from the confirmed copy | 400, 503, then a token. |
| GS-23 Model choice | A developer's own key is missing; another model is confirmed on one copy only, then on both | No model is offered until every listed copy confirms it; then that model is offered. |
| GS-25 Model choice checks live state | A shared-key model is confirmed on both copies; then its key file is replaced, or the gateway's definition moves on while the rows still list the old guard | Offered while unchanged; not offered after either change, as in the preview path. |

## `check_credentials` (task 002-02, Spec 002 ST4–ST5)

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| GS-26 Not in use | Run the guard-status part of `check_credentials` on SQLite with the per-copy check on, then off; then combine a guard-status problem, a warning or neither with otherwise passing credentials | `"not in use"` with no problem or warning; only a problem fails the check, a warning doesn't. |

## PostgreSQL roles

Roles as the guide creates them: a migration role owning the database, an app
role with the usual default table grants, an enroller approvals role and two
status roles with `default_transaction_read_only = on`, and one role without it.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| GS-PG-01 After migrate | Before the command, the app tries to write a row | Refused by row-level security; it can read. |
| GS-PG-02 Unsafe setup refused | Run the command as the app role; with a status role that isn't read-only by default; with a missing role; with a copy that names no role | Each is refused with its reason, changing nothing. |
| GS-PG-10 No role belongs to another | Make a status role a member of the other copy's, the app a member of a status role, or the approvals role a member of the app, each without inheriting | Refused, naming the membership; after it is revoked the command succeeds. |
| GS-PG-03 Idempotent | Run the command twice | Both succeed with the same result. |
| GS-PG-04 Own row only | A status role writes its row without, then with, `BEGIN READ WRITE`; then inserts, upserts, updates and reads the other copy's row; renames its row; deletes it | Read-only refusal, then success (twice); the other copy's row can't be inserted, changed or seen; renaming and deleting are refused. |
| GS-PG-05 No other table | The approvals role and a status role read accounts and migration history and insert an approval; the status role reads approvals | Permission denied each time. |
| GS-PG-06 Approvals connection can't write | The approvals role reads approvals, updates one in its default transaction and in `BEGIN READ WRITE`, and reads or writes the status table | Read succeeds; read-only refusal; permission denied; permission denied. |
| GS-PG-07 App reads only | The app reads every row, then inserts, updates, deletes and truncates | Reads both rows; every write is denied. |
| GS-PG-08 A copy left out | Run the command again with only copy 0 | Copy 1's role can no longer write; copy 0's still can. |
| GS-PG-09 End to end | An enroller process (read-only approvals role, copy 0's status role) confirms, clears and confirms its row, tries copy 1's row and an approval change; the app process reads the rows and tries to write | Its own row is confirmed and cleared; copy 1 and the approval change are refused; the app sees copy 0's models, refuses unconfirmed copy 1 and can't write. |
| GS-PG-11 `check_credentials` reports each copy | After the command, copy 0 has a confirmed row from 90 minutes ago and copy 1 an unconfirmed one; the app role runs the check with the per-copy check on and both copies listed | Row-level security `on`, policies `as set`, app `reads only`; both roles `limited`; copy 0 `confirmed` with its time, an age of about 90 minutes and its model's id and fingerprint; copy 1 `not confirmed`, which only warns. No password or digest is printed. |
| GS-PG-12 Unsafe or unusable role | Copy 0's status role bypasses row security, creates roles, belongs to the migration role or to copy 1's role, isn't read-only by default, reads another table, can delete rows, can't log in, has an expired password or has no CONNECT; separately, the app role can insert and delete rows | Copy 0's role is `unsafe` or `cannot log in` with one sentence naming the fault (the migration role's inherited privileges are summarised in a second one); copy 1 stays `limited`; the app is `unsafe`, naming its extra privileges. Each passes again once undone. |
| GS-PG-13 Changed setup | Row security turned off; an extra policy; the command run again without copy 1, or pairing its role with a copy no longer listed; copy 1's row deleted | Each fails with its sentence: row security `off`; policies `changed` and both copies `not paired`; copy 1 `not paired` (with a warning naming the stale pairing); copy 1 `not recorded`. |
| GS-PG-14 The command | Run `manage.py check_credentials` as the app role with copy 0's role able to bypass row security; then the guard-status part with the per-copy check off | Exit 1, `"passed": false`, copy 0 `unsafe` with one problem, no password in the output; then `"not in use"`. |
