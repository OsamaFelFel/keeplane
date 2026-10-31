# Projects screen

PRJ-UI-01 to PRJ-UI-04 use deliberate API fixtures and never change preview
records. PRJ-UI-05 uses the running server with no fixtures; it changes records
and restores them.

| Case | Action | Expected result |
| --- | --- | --- |
| PRJ-UI-01 | Open Projects with one first-use record. | The admin shell selects Projects; the row shows who used it, Not yet and its current class. Next is disabled on the last page. |
| PRJ-UI-02 | Open at 320px, focus the table and press ArrowRight, then open and close Menu. | Only the table scrolls sideways; the page stays within the viewport and Projects remains reachable through the menu. |
| PRJ-UI-03 | At320px, open Set class, choose Public and save. | The class changes once, the dialog fits, and focus returns to Set class. |
| PRJ-UI-04 | Lose the save response after the request, then press Check. | The form stays disabled until readback confirms the current class. No second write is sent. |
| PRJ-UI-05 | Spec 005 ST19 "Set a class": a new developer's first use registers a project. The admin signs in, finds it in Projects, chooses Set class, picks Confidential and saves, then reloads the page. | The row shows Confidential before and after the reload, and the server reads back Confidential. Afterwards the class is cleared, the developer removed and the data-class mode restored; the project record stays with no class. |

PRJ-UI-05 skips, with the reason, when Keeplane is running without a reachable
model gateway, because Set class lists the classes through it. The gateway path
for the same class is in the [live project-class cases](../e2e/project-classes-live-cases.md).
