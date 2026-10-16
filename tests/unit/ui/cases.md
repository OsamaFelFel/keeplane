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

## Projects

- Admins can see project names, onboarding state and who used each project.
- Class columns disappear while classes are off.
- Search returns to the first bounded page; Previous and Next follow server results.
- Empty and unavailable states are clear. Failed reloads do not leave stale rows visible.
- Set class submits the explicit choice through the protected action, including React StrictMode.
- A refused write keeps the choice. A lost reply or ten-second timeout offers Check without repeating the write.
- Readback confirms the saved class. If classes were turned off, the dialog keeps the result uncertain rather than clearing an assignment.
