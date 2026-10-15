# Spec 004 local model removal cases

Run against the protected Docker preview with its real agentgateway. The
automated runner creates distinct trial models and removes them afterward.
These cases cover the existing no-key local source; shared and personal keys
and routing references remain separate work.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| REMOVE-01 | Add a model through Keeplane with Public approval. | The model answers and Keeplane records that it owns this gateway registration. |
| REMOVE-02 | Try to remove that model without the admin action header. | The request is refused and the model stays approved and registered. |
| REMOVE-03 | Confirm Remove model for the Keeplane-owned model. | Keeplane stops sending work, deletes its gateway registration and removes its approval. |
| REMOVE-04 | Register another model directly in the gateway, then set it up and remove its Keeplane setup. | The model stays in the customer's gateway, shows as added outside Keeplane, and receives no Keeplane work. |
| REMOVE-05 | Change a Keeplane-owned model directly in the gateway, then try to remove it through Keeplane. | Keeplane refuses to delete the changed gateway definition. The old approval permits no work. |
| REMOVE-06 | Set up that changed model again, then remove its setup. | Its ownership has become unproven, so Keeplane removes only its approval and preserves the gateway definition. |
| REMOVE-07 | Open the admin page. | It serves the removal dialog and ownership-aware UI script. |
| REMOVE-08 | Enable settings Audit, remove an owned model, then inspect its records. | The removal records first-admin and the gateway deletion; the prior Audit setting is restored. |

Visual interaction is covered by MO-UI-04 in `tests/browser/models.spec.ts`,
which opens the real React dialog and verifies that removing an outside setup
keeps its gateway model. REMOVE-07 checks that the application bundle is served;
it does not claim to execute the dialog.
