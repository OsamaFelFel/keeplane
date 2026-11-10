# A coding task stopped by an outage

**Edition:** Open Source. Spec 009 ST29 and ST30, task 009-15, ADR 028. Unit
cases for what `keeplane code` says when the gateway, or Keeplane behind it,
is down while a task runs. The live cases are in
[sign-in restart and outage cases](../e2e/sign-in-restart-outage-cases.md).

```sh
.venv/bin/python -m pytest tests/unit/test_cli_service_outage.py
```

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| OUT-01 | The runtime sends a call through the turn's usage relay and nothing answers at the gateway's address. | The relay answers 502, counts one call the gateway never answered, and counts no usage. |
| OUT-02 | A task's first call can't reach the gateway. | The CLI says "Keeplane's gateway can't be reached right now, so this task stopped and nothing was sent. Try again in a few minutes, or ask your admin to check the gateway." It doesn't say the model is unavailable or ask for other models. |
| OUT-03 | Earlier calls of the task went out, then the gateway can't be reached. | The same message with "nothing more was sent". |
| OUT-04 | The gateway refuses (403) or fails (503) a call, and right afterwards Keeplane doesn't answer, or answers 503. | The CLI says "Keeplane isn't available right now, so this task stopped and nothing more was sent. Try again in a few minutes, or ask your admin to check Keeplane." Not an expired sign-in, and not a model that is down. |
| OUT-05 | The gateway refuses (403) or fails (503) a call while Keeplane answers. | The CLI keeps its usual message: a 503 is a model that is down (Spec 004 ST16); a 403 adds no outage message. |
| OUT-06 | The gateway answers 401. | The expired sign-in message still applies (ST29); no outage message. |
