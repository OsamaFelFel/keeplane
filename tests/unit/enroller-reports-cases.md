# Enroller reports cases

Run `.venv/bin/python -m pytest tests/unit/test_enroller_reports.py`
(issue #253, ADR 027). The cases drive the model enroller's loop
(`manage.py run_model_enroller`) with a stand-in that returns set results for
each pass, and read the lines it writes. Nothing is enrolled; no gateway,
database or Docker is used. Waiters such as the preview sign-in live suite read
the last of these lines to know the enroller has settled.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ER-01 | A change is held, then the hold ends and leaves no model enrolled (for example models left on the volume after a full reset), then nothing changes. | The loop reports the hold once, then `No model is enrolled for protected access.` once. The last line no longer says a change is waiting. |
| ER-02 | A change is held, then the hold ends by withdrawing every model. | The hold, then `No model is enrolled for protected access.` |
| ER-03 | A change is held, then the hold ends and two models are enrolled, then nothing changes. | The hold, then `Protected access is ready: 2 models are enrolled.` once. |
| ER-04 | One model is enrolled, a change is held, then the change is undone so the hold ends with the same model, then nothing changes. | `Protected access is ready: 1 model is enrolled.`, the hold, then `Protected access is up to date: 1 model is enrolled.` once. |
| ER-05 | Passes that find nothing new: no model twice, the same model after enrolling it, and a hold that lasts several passes. | Each state is reported once; repeated passes write nothing. |
| ER-06 | Check each pair of passes the loop compares. | Only a first pass, a change of state or models, or the end of a hold is reported. |
