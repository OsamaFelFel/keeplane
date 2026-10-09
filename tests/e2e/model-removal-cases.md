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

Visual interaction checks use `python3 tests/e2e/ui_fixture_server.py` and
`http://127.0.0.1:14210/`. This loopback fixture serves the actual admin UI
with one Keeplane-owned and one outside model; it never writes to the gateway.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| REMOVE-UI-01 | Edit `keeplane-visual-trial` and choose Remove model. | The confirmation names the model, says it will be removed from the gateway, and has **Remove model** and **Cancel** actions. |
| REMOVE-UI-02 | Cancel that confirmation and open it again. | The same complete confirmation appears without a script error. |
| REMOVE-UI-03 | Edit `outside-visual-trial` and choose Remove Keeplane setup. | The confirmation says the model stays in the gateway and its action is **Remove setup**. |

The ownership rule is deliberately conservative: models registered outside
Keeplane remain outside models. Removal of a model referenced by future complexity or
persona routing is not yet implemented because those routing settings do not
exist in the local preview.
