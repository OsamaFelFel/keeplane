# Managed launcher

**Edition:** Open Source. Spec 009 ST29/ST30, ADR 027 and ADR 028.
Run `pytest tests/unit/test_guarded_runtime_launcher.py tests/unit/test_runtime_preparation.py`.
`deploy/local/up.py` runs `guarded_runtime.install()` on every start. Docker is
substituted: the cases record the Compose commands. Unit ownership calls are
substituted because the host cannot chown files to the container account.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GRL-01 | Install with two named models. | The enroller, gateway and app stop first; disabled enrollment is prepared; a new gateway process starts; the app migrates, both fixed CLI clients (browser, then device) are registered, the app starts and is checked; then exactly the named models are enrolled and the model enroller starts last. |
| GRL-02 | Install with no named models, as `up.py` does. | The same steps, with both CLI clients registered and no separate enrollment command: the model enroller, started last, enrols every saved approval on its first pass. No sign-in switch or image is passed on the command line; the Compose files set both. |
| GRL-03 | Make each step fail in turn: the same gateway process comes back, preparation, migration, client registration, enrollment, or starting the enroller. | Only the model enroller and the managed gateway are stopped; nothing is removed (no `down`, no volumes); the error says the gateway is stopped and never repeats the step's own output. |
| GRL-04 | Enrollment fails and stopping the gateway fails too. | The error says stopping the gateway could not be confirmed. |
| GRL-05 | Enrollment times out. | Only the managed gateway and enroller are stopped. |
| GRL-06 | Read the enroller's first report after start: it comes after a blank log, at once, or never. | The first report line is returned (for example `No model is enrolled for protected access.` or `Protected access is ready: 1 model is enrolled.`); with none within the wait, nothing is returned and the launcher says to check the enroller's log. |

The runtime preparation cases check current operator hashes, stable callback
credentials and disabled enrollment before file validation.
`docker compose -f compose.yaml -f deploy/local/runtime.yaml config --quiet`
checks the schema without starting anything. The live start is covered by the
[preview sign-in cases](../e2e/preview-sign-in-live-cases.md).
