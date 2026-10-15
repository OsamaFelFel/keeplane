# React Models cases

These cases use the product team's Models, Add model and Edit model designs. They run against the actual React build with controlled API responses; the local end-to-end suite separately exercises the gateway and model API.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| MO-UI-01 | Open Models with one approved model and one model added outside Keeplane, then narrow the browser to 320px and open Add model. | The page shows the different setup states, keeps the page inside the viewport, and its provider dropdown and address field are both at least 44px tall. |
| MO-UI-02 | Find a model on a local runner and add it while data classes are off. | The active context is shown, no class is requested, and the model appears in the table. |
| MO-UI-03 | Try to add a shared cloud key to a customer-run gateway that lacks key delivery. | The clear error appears in the Add dialog; the model and key entries stay in place for review. |
| MO-UI-04 | Remove Keeplane setup for a model the customer put in the gateway. | Its gateway entry remains listed as added outside Keeplane and receives no Keeplane work. |
