# Spec 004 model approval trial cases

Run against the protected Docker preview at `http://127.0.0.1:3000` after
`deploy/local/up.py` and `test_local.py`. `local-fixture` is a
file-owned gateway model, and `test_local.py` registers `second-local` through
the gateway API. Both must be unapproved before the run. The runner is
[`test_model_approval.py`](test_model_approval.py); it removes only approvals
it creates and writes a JSON observation report.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| MODEL-01 | Open Models and routing as an admin. | The outside model is listed with no key or approved classes and has a Set up action. |
| MODEL-02 | Ask the outside model to do work before setup. | Keeplane refuses the call before forwarding it. |
| MODEL-03 | Try setup without the admin action header. | Keeplane refuses the change. |
| MODEL-04 | Try an unsupported key choice and an unknown class. | Both are refused; the model stays unapproved. |
| MODEL-05 | Set up the model with no key and Public and Internal approval. | Keeplane checks it answers, records the approval, and shows those classes. |
| MODEL-06 | Ask the approved model to do work. | The model answers through Keeplane. |
| MODEL-07 | Restart the Keeplane Docker app. | The approval remains and the model can still answer. |
| MODEL-08 | Remove Keeplane's approval. | The model remains in the gateway, appears as outside again, and gets no Keeplane work. |
| MODEL-09 | Approve a dynamically registered gateway model, restart the app, and ask it to work. | Its approval survives restart and the model answers. |
| MODEL-10 | Try to register a gateway model without the admin action header. | The protected preview refuses the change. |

The test uses a file-owned fixture, so it does not prove cloud provider keys,
model replacement in a customer gateway, data-class enforcement for projects,
or the developer CLI. Those need their own cases when the related surfaces are
implemented. The catalog also binds an approval to the gateway model
definition; `test_model_catalog.py` checks that a changed endpoint cannot match
the old approval even if the model name stays the same. A live replacement in
a customer gateway remains to be tested.
