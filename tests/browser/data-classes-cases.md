# Data Classes browser cases

These cases use a real Chromium browser and the locally built React UI. The network replies for class settings and models are controlled so the screen can be checked without changing the owner's trial data. Run with `cd tests/browser && npm test -- data-classes.spec.ts` while the Docker preview is up.

| ID | Plain-English case | Expected result |
| --- | --- | --- |
| DC-UI-01 | Open Data Classes with the mode off, turn it on, check the 1280px screenshots and 320px width, then turn it off again. | The off screen has no class table or Add button. On shows the three starter classes. The narrow page does not scroll horizontally. Turning it off hides class controls again. |
| DC-UI-02 | Open an on-mode Data Classes screen, add Restricted, and leave the available model unchecked. | Restricted appears with no approved model; the UI does not approve a model by default. |
| DC-UI-03 | Open Models and routing while data classes are off, then open Add model and Set up model. | The approval column and both class selection fields are hidden. |

The live API and storage cases are in [Data Classes cases](../e2e/cases.md) and [the 005-01 run](../e2e/runs/2026-10-10-optional-data-classes.md).
