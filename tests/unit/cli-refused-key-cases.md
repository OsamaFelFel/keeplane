# A refused key found when a task fails

Spec 004 ST11 "A refused key" (governance issue #63, question 4; ADR 030; task
009-11). Journey: none (Spec 004). The gateway passes the provider's answer on,
so a provider that turns the developer's own key down shows in the runtime's
error events as a 401 or 403, like the gateway's own refusals. The CLI then asks
the server to recheck the saved key, and only the server's verdict counts. Run
`python -m pytest tests/unit/test_cli_refused_key.py`; the
[integration cases](../integration/cli-refused-key-cases.md) check the same with
the real server and provider fixture.

| Case | Situation | Expected result |
| --- | --- | --- |
| RK-01 | The runtime's events after a failed task | An error event with a 401 or 403 status may be a refused key. Other statuses, a 401 outside an error event, a status that isn't a number, and lines that aren't events are not. |
| RK-02 | The model uses the developer's own key and a key is saved | The CLI reads the key list (no provider call), then asks the server to check the key, sending only the model ID. The key counts as refused only if the server's check says `refused`; a key already listed as refused needs no new check. |
| RK-03 | No own key is saved, the model uses a shared key or none, or the project doesn't allow it | The CLI reads the key list only. It asks for no check and says nothing about a key. |
| RK-04 | The server can't confirm: an expired sign-in, an older server, an outage, a provider that can't be reached, or an answer the CLI can't trust | Not a refused key. The task's own error stands. |
| RK-05 | `keeplane code` fails with a 401 or 403 and the server confirms the refusal | The runtime's output still shows. The CLI says "The provider refused your own key for coder, so this task stopped. Replace it with `keeplane keys set --model coder`. Run `keeplane keys list` to see your keys." It is not reported as an expired sign-in or a model outage, and no other models are asked for. No credential is printed. |
| RK-06 | A 401 or 403 the server doesn't confirm as a refused key | A 401 is still an expired sign-in (ST29), with the same message as before. A 403 on a key the provider still accepts says nothing about the key. |
| RK-07 | A task that succeeds, or fails with another status such as a 503 | No key list or check is asked for; a model that is down keeps its own message (ST16). |
