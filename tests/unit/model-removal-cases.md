# Model removal backend cases

Run `python3 tests/unit/test_model_removal.py`. The existing
[live removal cases](../e2e/model-removal-cases.md) test the same behavior
through the protected Docker and kind previews.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| MR-01 | Remove Keeplane setup from a customer-added model. | Its approval and settings audit change are recorded; no gateway delete is sent. |
| MR-02 | Change a Keeplane-owned model in the gateway before removal. | The removal is refused and both the model and approval remain. |
| MR-03 | Make the gateway reject removal of a Keeplane-owned model. | Keeplane retains the approval and reports the gateway failure. |
| MR-04 | Remove an unchanged Keeplane-owned model. | The gateway registration and Keeplane approval are both removed. |
| MR-05 | Remove an owned model with a Keeplane-managed shared key. | The key file is removed after confirmed gateway deletion. |
| MR-06 | Send a model deletion through the gateway adapter. | The request uses DELETE and the management credential, not the runtime credential. |
| MR-07 | Remove an outside model using the real local catalog with settings Audit on. | The removal and its Audit record commit together. |
