# A refused key found when a task fails, on the real server

Spec 004 ST11 "A refused key" (governance issue #63, question 4; ADR 030; task
009-11). Journey: none (Spec 004). After a task's 401 or 403, the CLI's own
request code (`server_connection.request`) reaches the real Django key routes
over HTTP on a threaded local server. The server checks the saved key with the
authenticated provider fixture of the [key check cases](developer-key-recheck-cases.md).
The [unit cases](../unit/cli-refused-key-cases.md) cover spotting the refusal
and what `keeplane code` prints. Run
`python -m pytest tests/integration/test_cli_refused_key.py`.

| Case | Situation | Expected result |
| --- | --- | --- |
| RK-INT-01 | The provider fixture turns the saved key down with a 401 or a 403 | The CLI's recheck reports a refused key after one provider request with the saved key, and the key list the CLI reads (what `keeplane keys list` prints) shows it as `refused`. A second failed task needs no new provider request. |
| RK-INT-02 | The provider still accepts the key, or is down | Not a refused key: the key stays `added` and no verdict is recorded. |
| RK-INT-03 | The developer's sign-in has ended | Not a refused key, and the provider is never contacted. |
