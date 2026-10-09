# Live gateway model-replacement cases

Run after the protected Docker account preview is started. The
[runner](test_model_replacement.py) creates a uniquely named gateway model
against the fixed-answer local fixture and removes its own model and approval
at the end. It does not change the user's existing models.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| REPLACE-01 | An external gateway admin adds a new model. | Keeplane lists it as outside and sends it no work. |
| REPLACE-02 | A Keeplane admin approves that model for Public. | It answers through the protected Keeplane API. |
| REPLACE-03 | The gateway admin changes the model's upstream definition under the same name. | Keeplane rejects the next call; the gateway still lists the model, but Data classes no longer calls it approved and refuses a new association to it. |
| REPLACE-04 | The gateway admin changes the definition back to its original value without Keeplane approval. | Keeplane still rejects it and Data classes still omits its approval because a gateway update occurred. |
| REPLACE-05 | The Keeplane admin sets up the model again. | The current gateway definition answers through Keeplane and Data classes lists its approval again. |

This checks a completed gateway update followed by a new short request. It
does not close the race between Keeplane's definition check and the gateway's
forwarding of the same request; the release needs gateway-side policy or an
equivalent atomic binding.
