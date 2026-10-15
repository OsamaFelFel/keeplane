# Projects screen

These browser cases use deliberate API fixtures and never change preview records.

| Case | Action | Expected result |
| --- | --- | --- |
| PRJ-UI-01 | Open Projects with one first-use record. | The admin shell selects Projects; the row shows who used it, Not yet and its current class. Next is disabled on the last page. |
| PRJ-UI-02 | Open at 320px, focus the table and press ArrowRight, then open and close Menu. | Only the table scrolls sideways; the page stays within the viewport and Projects remains reachable through the menu. |
| PRJ-UI-03 | At320px, open Set class, choose Public and save. | The class changes once, the dialog fits, and focus returns to Set class. |
| PRJ-UI-04 | Lose the save response after the request, then press Check. | The form stays disabled until readback confirms the current class. No second write is sent. |
