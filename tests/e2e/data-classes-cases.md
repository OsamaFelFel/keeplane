# Spec 005 starter data-class trial cases

Run after the protected Docker preview is started. The live runner
[`test_data_classes.py`](test_data_classes.py) starts with an unapproved
`local-fixture`, creates one temporary class and one temporary model approval,
then removes only what it created. It records the HTTP observations as JSON.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| CLASS-00 | Turn data classes off and try to add a class. | The list is empty and the change is refused while the mode is off. |
| CLASS-10 | While classes are off, set up a gateway model without selecting a class, then turn classes on. | The model is set up and can be used while off, and the later on state gives it no implicit class approval. |
| CLASS-01 | Turn data classes on and open the React admin page. | Public, Internal and Confidential appear, and the page opens. |
| CLASS-09 | Set up a model for Public, turn classes off, then on again. | Model setup remains while off and its Public approval returns unchanged when reenabled. |
| CLASS-02 | Set up a model, add a class, and select that model. | The class lists the model and the model lists the class as approved. |
| CLASS-03 | Try to add the same class name with different capitalization. | The duplicate is refused. |
| CLASS-04 | Try to select a model that has not been set up. | The class is not saved. |
| CLASS-05 | Rename the class while keeping its approved model. | Both the class list and model approval show the new name; the old name disappears. |
| CLASS-06 | Restart the protected Keeplane app. | The renamed class and its model approval remain. |
| CLASS-07 | Remove the temporary class. | It disappears from the list and from the model's approved classes; the model remains approved for Public. |
| CLASS-08 | Try to change classes without the admin action header. | Keeplane refuses the change. |

`test_data_classes_store.py` separately checks that a new store starts off,
turning on creates the starters, a class assigned to a project cannot be
removed, and removing a model's last approved class keeps its Keeplane setup
with an empty approval list. A model set up while classes are off receives no
class approval after the mode is turned on. The current release has no Projects screen
or project assignment API, so the project-in-use case uses an isolated database
fixture. Personal-data detection and project routing are not implemented by
this trial and need their own end-to-end cases.
