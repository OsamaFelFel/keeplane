# React Models cases

These cases use the product team's Models, Add model and Edit model designs. They run against the actual React build with controlled API responses; the local end-to-end suite separately exercises the gateway and model API.

- Personal Add hides the shared-key field, sends only the Personal choice and
  keeps the selected model/choice after a refused provider check.
- Personal Edit names the developer-owned choice, explains the provider check,
  preserves that choice when saving classes and offers no shared-key replacement.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| MO-UI-01 | Open Models with one approved model and one model added outside Keeplane, then narrow the browser to 320px and open Add model. | The page shows the different setup states, keeps the page inside the viewport, and its provider dropdown and address field are both at least 44px tall. |
| MO-UI-02 | Find a model on a local runner and add it while data classes are off. | The active context is shown, no class is requested, and the model appears in the table. |
| MO-UI-03 | Try to add a shared cloud key to a customer-run gateway that lacks key delivery. | The clear error appears in the Add dialog; the model and key entries stay in place for review. |
| MO-UI-04 | Remove Keeplane setup for a model the customer put in the gateway. | Its gateway entry remains listed as added outside Keeplane and receives no Keeplane work. |
| MO-UI-05 | Set up an outside model, have the first save refused, save again, then edit its approved classes. | The class choices are kept after the refusal, the retry sets it up and the row shows the new classes (MODEL-01, EDIT-01). |
| MO-UI-06 | Add an OpenAI model set to each developer's own key while the provider check is refused, then again when it answers. | No shared-key field is shown or sent; after “OpenAI didn't answer.” the model and choice stay; the second add shows the model. |
| MO-UI-07 | Edit a model set to each developer's own key. | The dialog names the developer-owned choice, explains the provider check, offers no shared-key replacement and keeps the choice when classes are saved. |
| MO-UI-08 | Open Change for Complex with the keyboard, save another model, then choose Use Keeplane's pick; narrow to 320px. | The Change a level dialog is at most 560px wide with a 44px Model select and names Keeplane's pick; the row shows “changed by an admin”, then “Keeplane's pick” again; two protected requests are sent; the page stays inside 320px. |
| MO-UI-09 | Choose Remove model for a model an admin-changed level uses. | The Remove model: in use dialog lists “Complexity level: Standard” and closes; no removal request is sent. |
| MO-UI-10 | With no rules yet, open Add rule with the keyboard, choose Architect and a model, add it; narrow to 320px. | The Add persona rule dialog is at most 560px wide with 44px persona and model selects; the rule shows as “Persona is Architect” with the model and a notice; one protected request is sent; the page stays inside 320px. |
| MO-UI-11 | Choose Remove model for a model a persona rule uses. | The Remove model: in use dialog lists “Persona rule: Architect” and closes; no removal request is sent. |

MO-UI-05 covers MODEL-01/EDIT-01 dialog behavior: set up an outside model, retain its class choices after a refused save, retry, edit its approvals and see the updated row. The Python API suites verify storage and authorization separately.
