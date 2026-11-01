# Personal-data detection on the gateway checks

Spec 005 ST20. Run `python -m pytest tests/integration/test_personal_data_routing.py`
with isolated Django storage. A deterministic fake detector finds one invented
email; the models are `open` (Public), `private` (Confidential) and `both`.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| PR-01 | With data classes on and detection never changed, send a request with personal data. | Detection is off with Confidential chosen; nothing is inspected and the route is unchanged. |
| PR-02 | Turn detection on; send a request with personal data from a project with no class to each model, then a clean one. | Only models approved for Confidential are allowed; any other model gets "This request is handled as Confidential and <model> isn't approved for it, so nothing was sent. Run it with a model approved for Confidential, or ask your admin to approve one."; the clean request is unchanged; responses carry only actor, project and model. |
| PR-03 | Detection handles requests as Public; the project is Confidential. | A held request needs a model approved for both classes; the project's own limit still applies to clean requests. |
| PR-04 | The detector is slow, down or fails; the check carries no messages; a message has an image, a non-list `tool_calls` or an unknown field such as `audio`. | Each request is handled as the detection class; none errors. |
| PR-05 | Choose Public under Handle it as. | Requests with personal data go only to Public models. |
| PR-06 | Turn data classes off with detection on; separately, turn detection on after the unlocked read. | With classes off nothing is inspected or changed; a request not inspected while detection read as off is still held. |
| PR-07 | Send requests to the selected-model check, then to the route check, on a customer-run gateway. | The final check inspects too but marks nothing for Audit. The route check marks each held request once, refused or allowed, with its class and reason; a clean request is not marked. |
| PR-08 | Send long messages, `null` messages (what the gateway sends for a body over 1 MiB), padded metadata and a body over 8 MiB. | Long messages are checked; `null` messages are held; metadata alone keeps its 4 KiB limit; only a body over 8 MiB, which a gateway with the size guard never sends, is refused. Unknown fields are still refused. |
| PR-09 | Send personal data and read the responses. | No request text appears in any response. |
| PR-10 | Send invalid settings, choose a missing class, remove detection's class while detection is on and after it was turned off, turn classes off. | Invalid settings are refused; Confidential is the default; the class detection has been set to can't be removed, even while detection is off ("Personal-data detection still uses this class. Choose another class under Handle it as first, then remove it."); detection can't be changed while classes are off and its settings are kept. |
| PR-11 | Through the admin API, read and change detection with the Audit **Settings changes** switch on; send a change without the admin UI's header. | The listing shows detection; Audit records "Turned personal-data detection on; detected requests handled as Confidential", "Changed the class for detected requests: Confidential to Internal" and "Turned personal-data detection off"; the change without the header is refused. |
| PR-12 | Turn detection on while the detector isn't installed or the install doesn't send messages; then lose the detector after it was on. | Turning on is refused with "Personal-data detection isn't installed. Install it, then turn this on."; once on, the class can still change and it can be turned off; requests without messages are held. |
| PR-13 | With detection off, send checks without messages, padded metadata, and an over-64 KiB request to another route. | Decisions and responses are as before detection existed; metadata keeps its 4 KiB limit; other routes keep the 64 KiB limit. |
