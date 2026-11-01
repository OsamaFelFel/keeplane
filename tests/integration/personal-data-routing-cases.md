# Personal-data detection on the gateway checks

Spec 005 ST20. Run `python -m pytest tests/integration/test_personal_data_routing.py`
with isolated Django storage. A deterministic fake detector finds one invented
email; the models are `open` (Public), `private` (Confidential) and `both`.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| PR-01 | With data classes on and detection never changed, send a request with personal data. | Detection is off with Confidential chosen; nothing is inspected and the route is unchanged. |
| PR-02 | Turn detection on; send a request with personal data from a project with no class to each model, then a clean one. | Only models approved for Confidential are allowed, with "This request is handled as Confidential, and this model isn't approved for it" otherwise; the clean request is unchanged; responses carry only actor, project and model. |
| PR-03 | Detection handles requests as Public; the project is Confidential. | A held request needs a model approved for both classes; the project's own limit still applies to clean requests. |
| PR-04 | The detector is slow, down or fails; the check carries no messages; a message has an image. | Each request is handled as the detection class. |
| PR-05 | Choose Public under Handle it as. | Requests with personal data go only to Public models. |
| PR-06 | Turn data classes off with detection on; separately, turn detection on after the unlocked read. | With classes off nothing is inspected or changed; a request not inspected while detection read as off is still held. |
| PR-07 | Send requests to the selected-model check on a customer-run gateway. | The final check inspects too, and a held request reaches the held-request Audit hook once with its class and reason. |
| PR-08 | Send long messages, padded metadata and a body over 4 MiB. | Messages up to 4 MiB are checked; metadata alone keeps its 4 KiB limit; a larger body is refused. Unknown fields are still refused. |
| PR-09 | Send personal data and read the responses. | No request text appears in any response. |
| PR-10 | Send invalid settings, choose a missing class, remove the class in use, turn classes off. | Invalid settings are refused; Confidential is the default; a class used by detection can't be removed; detection can't be changed while classes are off and its settings are kept. |
| PR-11 | Through the admin API, read and change detection with the Audit **Settings changes** switch on; send a change without the admin UI's header. | The listing shows detection; each change is recorded in plain words; the change without the header is refused. |
