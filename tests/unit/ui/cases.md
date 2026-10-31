# React UI unit cases

Run `npm run test:unit` from `components/admin-ui/`. Vitest discovers test
files in this top-level `tests/unit/ui/` directory; component source has no
colocated tests.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| UI-01 | Open Create user, enter a too-short username and password, then submit. | Developer is selected by default, validation explains both inputs, and no request reaches the account API. |
| UI-CSRF-01 | Submit a browser change. | A fresh masked token is sent with same-origin credentials and the original JSON headers. |
| UI-CSRF-02 | Fail token bootstrap. | No mutation request is sent. |
| UI-CSRF-03 | Refuse or disconnect a mutation. | The write is not repeated automatically. |
| UI-CSRF-04 | Supply a different-origin URL. | No token or request is sent to that origin. |
| MO-UI-COUNT | Open Models with zero, one and two personal-key registrations. | Each personal row shows its server count below “Each developer's own”; shared models show no count. |
| CL-UI-01 | Open Models with two levels on Keeplane's pick and one changed by an admin. | The Complexity table marks each model “Keeplane's pick” or “changed by an admin”. |
| CL-UI-02 | Change Simple to another model. | The dialog offers only set-up models, names Keeplane's pick, disables Use Keeplane's pick for a level on Keeplane's pick, sends one protected request and shows the change. |
| CL-UI-03 | Choose Use Keeplane's pick on an admin-changed level. | The request sends no model and the page says the level uses Keeplane's pick again. |
| CL-UI-04 | The server refuses a level change. | The dialog stays open with the reason. |
| CL-UI-05 | Choose Remove model for a model an admin-changed level uses. | “[model] is still in use” lists “Complexity level: Complex”; no removal request is sent. |
| CL-UI-06 | A level was changed to a model after the page loaded, then the admin removes it. | The server's 409 opens the same in-use dialog with the level it names. |
| CL-UI-07 | No model is set up. | Each level says “No model set up yet” and Change is disabled. |
| CL-UI-08 | An admin's model isn't set up now. | The row explains that the admin's model isn't set up. |

## Projects

- Admins can see project names, onboarding state and who used each project.
- Class columns disappear while classes are off.
- Search returns to the first bounded page; Previous and Next follow server results.
- Empty and unavailable states are clear. Failed reloads do not leave stale rows visible.
- Set class submits the explicit choice through the protected action, including React StrictMode.
- A refused write keeps the choice. A lost reply or ten-second timeout offers Check without repeating the write.
- Readback confirms the saved class. If classes were turned off, the dialog keeps the result uncertain rather than clearing an assignment.
