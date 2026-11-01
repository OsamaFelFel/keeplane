# Recording model answers

These cases cover spec 006 ST21 "Model answers" as the owner decided in
governance issue #36: "sent" is enough. When the **Model answers** switch is
on, Keeplane writes one record each time its final model check lets a
developer's request through to a model. The record names the time, the
developer, the project and the model. A record means the request was sent, not
that the model answered.

MA-01 to MA-08 call the private installed-runtime checks a managed gateway
uses, over HTTP in the test process, on SQLite, with a synthetic gateway
reader. MA-09 and MA-11 to MA-15 do the same for a customer-run (`existing`)
gateway, which calls only the shared check: `/internal/runtime/authorize` at
the route and `/internal/runtime/authorize/selected` on each model backend.
MA-16 checks that each mode has exactly one recorder. MA-17 runs in both
modes without an enclosing test transaction, so it sees only what is
committed. MA-10 runs the record
producer in separate control-plane processes on a fresh database, on SQLite
and, when configured, PostgreSQL.

| Case | Given | Expected result |
| --- | --- | --- |
| MA-01 After install | A fresh install; a developer's request passes the entry check and the final check | The switch is off and no record is written. |
| MA-02 One record per request sent | The switch is on; the developer sends three requests, each passing the entry check and the final check | Three records, one per final check, under the developer's username, with a UTC time and `Request sent to model private; project Callback`. The entry check writes none. **Show: Model answers**, **Show: All** and search by developer, model or project find them; **Show: Settings changes** does not. |
| MA-03 Its own switch | Settings changes and held-back requests are on and model answers off; then only model answers on; then model answers off again | No record while it is off. Only a model-answer record while it is on, and no other kind. Turning it off stops new records; the earlier one stays. |
| MA-04 Refused request | The switch is on. The final check refuses a model that is not installed, an earlier definition, an unknown project, a signed-out developer, a wrong gateway credential, a prompt added to the check's body, and a project whose class no longer allows the model | Every request is refused and no record is written. |
| MA-05 Record cannot be written | The switch is on and writing the record fails, or reading the switch fails | The request is still allowed with the usual answer. No record is written and one warning is logged, without the session, gateway credential, definition fingerprint or database error text. The next request is recorded. |
| MA-06 No request text or keys | The switch is on; a shared-key model is sent a request whose headers carry a prompt | The one record holds no prompt, session token, gateway credential, definition fingerprint, provider key, key file name or password. |
| MA-07 Other developers | Two developers each send a request to their own project; the second also sends one with the first developer's project ID | Each record names the developer whose session sent the request, never the project's other users. |
| MA-08 Who can read them | A record exists | A developer and an anonymous caller are refused by the Audit records API and see no record. An admin sees it. |
| MA-09 Customer-run entry check | A customer-run gateway; the switch is on; a request passes `/internal/runtime/authorize` three times | No record: the gateway can call that check more than once per request. |
| MA-10 Stored for every app copy | Separate processes on SQLite and PostgreSQL. The producer runs with the switch off, then on, then while the write fails, then for a project that no longer exists | Only the "on" call writes a record; the two failures are logged and never raise. A second process sees the one record with the developer, model, project and a UTC time. |
| MA-11 Customer-run gateway | A customer-run gateway. The switch is off, then on while the developer sends three requests, each passing the shared entry check and the shared final check, then off again | Nothing while off. Three records, one per final check, under the developer's username, with a UTC time and `Request sent to model private; project Callback`; the answer is the usual decision. Turning it off stops new records. |
| MA-12 Customer-run refusal | A customer-run gateway; the switch is on. The shared final check refuses a model not set up, a model the project's class does not allow, an unknown project, a signed-out developer, a wrong gateway credential, a prompt added to the check's body, and a project whose class no longer allows the model | Every request is refused and no record is written. |
| MA-13 Customer-run failed write | A customer-run gateway; the switch is on and writing the record or reading the switch fails | The request is still allowed. No record is written and one warning is logged, without the session, gateway credential or database error text. The next request is recorded. |
| MA-14 Customer-run: no request text or keys | A customer-run gateway; the switch is on; the final check's headers carry a prompt | The one record holds no prompt, session token, gateway credential, key file name or password. |
| MA-15 Customer-run: other developers | A customer-run gateway; two developers each send a request to their own project | Each record names only the developer whose session sent it. |
| MA-16 One recorder per mode | The switch is on. A managed gateway sends one request through its installed checks, then also calls the shared final check; then the app runs as customer-run and the shared checks are used | Managed: one record; the shared final check is refused with `Managed gateways use the installed runtime checks` and writes nothing. Customer-run: the installed final check is refused and the shared final check writes one record. Two records in all, never two for one request. |
| MA-17 A request that later fails | The switch is on; in each gateway mode one request passes the final check, then the model fails and the developer's retry is refused because they signed out | The record is already committed when the final check answers, before the model is called. The failure does not remove it, and the refused retry adds none: one record. |

Run:

```sh
.venv/bin/python -m pytest tests/integration/test_model_answer_records.py
```

To run MA-10 on PostgreSQL as well, set the `KEEPLANE_TEST_POSTGRES_*`
variables described in the [persistence cases](audit-persistence-cases.md).
Without them that case is skipped and reported as skipped. The CI `postgres`
job sets them.

Not covered here: the native gateway calling the final check per attempt is
covered by the [installed-runtime cases](installed-runtime-cases.md) and the
managed installation; these cases do not start a gateway. No customer-run
gateway is wired to the shared checks in the local trial yet, so a live
customer-run run waits for the release gateway's integration.
