# A coding task stopped by an outage

**Edition:** Open Source. Spec 009 ST29 and ST30, task 009-15, ADR 028. Unit
cases for what `keeplane code` says when the gateway, or Keeplane behind it,
is down while a task runs or before it starts. The live cases are in
[sign-in restart and outage cases](../e2e/sign-in-restart-outage-cases.md).

```sh
.venv/bin/python -m pytest tests/unit/test_cli_service_outage.py
```

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| OUT-01 | The runtime sends a call through the turn's usage relay and nothing answers at the gateway's address. | The relay answers 502, counts one call the gateway never answered, and counts no usage. |
| OUT-02 | A task's first call can't reach the gateway. | The CLI says "Keeplane's gateway can't be reached right now, so this task stopped and nothing was sent. Try again in a few minutes, or ask your admin to check the gateway." It doesn't say the model is unavailable or ask for other models. |
| OUT-03 | Earlier calls of the task went out, then the gateway can't be reached. | The same message with "nothing more was sent". |
| OUT-04 | The gateway refuses a call before any model is tried, because Keeplane's check couldn't run: agentgateway's 403 "external authorization failed", or Keeplane's own 503 reason ("Keeplane storage is unavailable…", "Gateway authorization is unavailable") passed on. Right afterwards Keeplane doesn't answer, or answers 503. | The CLI says "Keeplane isn't available right now, so this task stopped and nothing more was sent. Try again in a few minutes, or ask your admin to check Keeplane." Not an expired sign-in, and not a model that is down. |
| OUT-05 | The gateway refuses (403) or fails (503) a call while Keeplane answers. | The CLI keeps its usual message: a 503 is a model that is down (Spec 004 ST16); a 403 adds no outage message. |
| OUT-06 | The gateway answers 401. | The expired sign-in message still applies (ST29); no outage message. |
| OUT-07 | The model was tried and failed (429 or 5xx, Spec 004 ST16) and Keeplane is down too. | The ST16 model message stays (D177): the outage message replaces it only when the request never reached a model. |
| OUT-08 | Before the task starts, Keeplane answers 502, 503 or 504. | `code` exits 1 with "Keeplane isn't available right now, so nothing was sent. Try again in a few minutes, or ask your admin to check Keeplane." The runtime never starts. |
| OUT-09 | Before the task starts, nothing answers at Keeplane's address. | The same message; the runtime never starts. |
| OUT-10 | Keeplane's certificate can't be checked. | Not an outage: "Cannot reach Keeplane securely; check the server and certificate configuration." stays. |
| OUT-11 | A failed call's error mentions one of the gateway's refusal reasons somewhere other than at the start of its message or answer body (a model's own error, or another field), and Keeplane is down too. Separately, the reason arrives only in the answer body the runtime keeps, with a generic message. | Only a message or body that starts with the gateway's own reason counts as Keeplane's check not running: the model's ST16 message stays for the first; the second is still Keeplane being down. |
| OUT-12 | Keeplane's TLS handshake succeeds, then the connection is cut while the CLI reads the answer (TLS end of file, closed, or a system error). Separately, another TLS error while reading (a bad record, a certificate error) or during the handshake. | A cut connection is an outage, so the "isn't available" messages apply. Any other TLS error keeps "Cannot reach Keeplane securely; check the server and certificate configuration." |
| OUT-13 | Keeplane answers the sign-in check, then answers 503 to the model list or the model choice; the CLI can't connect to the gateway, or can. | Can't connect: `code` exits 1 with "Keeplane's gateway can't be reached right now, so this task stopped and nothing was sent. Try again in a few minutes, or ask your admin to check the gateway." Can: the "Keeplane isn't available right now, so nothing was sent…" message. The runtime never starts. |
| OUT-14 | Keeplane answers 503 to the sign-in check itself while the gateway can't be reached either. | Keeplane is the cause: "Keeplane isn't available right now, so nothing was sent…". |
| OUT-15 | Keeplane's 503 carries its gateway reason ("Keeplane's gateway can't be reached"); another reason; a 502 or 504 from a proxy in front of Keeplane. | Keeplane's gateway reason gives the gateway message even if the gateway answers the CLI; the others need the CLI's own failed connection to the gateway, and a 502 or 504 never blames the gateway. |
| OUT-16 | The CLI checks whether anything accepts a connection at the gateway's address. | It only connects (nothing is sent): a listening port answers; a closed port or a name that doesn't resolve doesn't. |
