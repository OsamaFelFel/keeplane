# Spec 004 local model edit cases

Run against the protected Docker preview after starting the account stack.
`local-fixture` must be present and unapproved; the runner refuses to overwrite
an approval you already made. The [live runner](test_model_edit.py) removes
only the approval it creates and saves its HTTP observations as JSON.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| EDIT-01 | Open Models and routing, then set up the outside fixture for Public. | The model is approved for Public and the Edit dialog is available. |
| EDIT-02 | Edit the model's approved class to Internal. | The model answers the validation call and its listing shows Internal only. |
| EDIT-03 | Try an unknown class while editing. | The edit is refused and Internal remains approved. |
| EDIT-04 | Try to edit without the admin action header. | The edit is refused and Internal remains approved. |
| EDIT-05 | Remove the model's Keeplane setup. | The model stays registered in the gateway, shows Set up again, and Keeplane refuses to send it work. |

This covers editing and removing Keeplane's approval for an outside model that
needs no provider key. It does not remove a Keeplane-owned model from the
gateway or cover shared and developer-owned provider keys.
