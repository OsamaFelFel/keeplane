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
| MR-14 | As MR-09, for a model where each developer uses their own provider key. | The model is written back and re-pinned, and the admin is told developers must check their keys again, not that nothing changed. |
| MR-15 | The commit reports a failure after the gateway deletion, but the database kept it. | Keeplane sees the approval is gone, writes nothing back, deletes the shared key file and reports the removal as done. |
| MR-16 | The commit fails after the gateway deletion and the setup has changed since. | Nothing is written back and the changed setup is kept; the admin is told the model may be missing from the gateway and to check Models. |
| MR-17 | The model is written back, but the gateway readback fails, shows a different definition, or the approval can't be re-pinned (invalid classes or storage unavailable). | The approval is left as it was and the admin is told the model is back in the gateway and to check its setup in Models. |
| MR-18 | Another request removed the setup between reading it and removing it. | "Model setup not found" (404); no gateway delete or write back is sent. |
| MR-19 | The commit fails after the gateway deletion and reading the approval again fails too. | The model is still written back to the gateway, since Keeplane can't tell whether the removal was kept; the approval can't be re-pinned, so the admin is told the model is back in the gateway and to check its setup in Models. |
| MR-20 | Remove a Keeplane-added or customer-added model that admin-changed levels (Simple and Complex) use. | 409 with "[model] is still in use. Move these to another model first, then remove it." and the levels; the gateway is not read or asked to delete, and the approval stays. |
| MR-21 | A level is changed to the model after the first check, so the catalog finds it under the settings lock. | 409 with that level; nothing is removed from Keeplane or the gateway. |
| MR-22 | Remove a Keeplane-added or customer-added model that a persona rule (Architect) and an admin-changed level use, or only a persona rule (Frontend). | 409 listing the levels and the persona rules; the gateway is not read or asked to delete, and the approval stays. |
| MR-23 | A persona rule is changed to the model after the first check, so the catalog finds it under the settings lock. | 409 with that persona rule; nothing is removed from Keeplane or the gateway. |
