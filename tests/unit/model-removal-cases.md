# Model removal backend cases

Run `.venv/bin/python -m pytest tests/unit/test_model_removal.py`. The existing
[live removal cases](../e2e/model-removal-cases.md) test the same behavior
through the protected Docker and kind previews. MR-07 runs from
`tests/integration/test_audit_store.py`; the same failures against a real
SQLite and PostgreSQL database are
[SC-11](../integration/settings-change-record-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| MR-01 | Remove Keeplane setup from a customer-added model. | Its approval and settings audit change are recorded; no gateway delete is sent. |
| MR-02 | Change a Keeplane-owned model in the gateway before removal. | The removal is refused and both the model and approval remain. |
| MR-03 | Make the gateway reject removal of a Keeplane-owned model. | Keeplane retains the approval, writes nothing and reports the gateway failure. |
| MR-04 | Remove an unchanged Keeplane-owned model. | The gateway registration and Keeplane approval are both removed. |
| MR-05 | Remove an owned model with a Keeplane-managed shared key. | The key file is removed after confirmed gateway deletion. |
| MR-06 | Send a model deletion through the gateway adapter. | The request uses DELETE and the management credential, not the runtime credential. |
| MR-07 | Remove an outside model using the real local catalog with settings Audit on. | The removal and its Audit record commit together. |
| MR-08 | Remove a Keeplane-owned model while the approval or record write fails. | Storage is reported unavailable; no gateway delete is sent and the approval remains. |
| MR-09 | Remove a Keeplane-owned model; the gateway deletes it, then the database commit fails. | The same definition is written back to the gateway and the approval is bound to it again. The admin reads "Keeplane couldn't record the removal. The model is back in the gateway and nothing changed." |
| MR-10 | As MR-09, but the gateway also refuses the write back. | The admin is told the model may be missing from the gateway and to check Models. |
| MR-11 | As MR-09, for a model with a Keeplane-managed shared key. | The key file is kept, so the restored model can still use it. |
| MR-12 | Remove setup for a customer-added model while the record write fails. | No gateway delete or write back is sent. |
| MR-13 | Write a model back through the gateway adapter. | The request is a PUT of the previous definition to the management API. |
