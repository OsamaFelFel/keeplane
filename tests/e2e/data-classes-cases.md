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

`tests/integration/test_data_classes_store.py` separately checks that a new
store starts off, turning on creates the starters, a class assigned to a project
cannot be removed, and removing a model's last approved class keeps its Keeplane
setup with an empty approval list. A model set up while classes are off receives
no class approval after the mode is turned on. The same steps through the admin
HTTP API are the [data class admin cases](../integration/data-class-admin-cases.md).

## Spec 005 scenarios (ST18, ST19, ST20)

Each scenario in Spec 005 and the cases that prove it. CLASS cases are above.
DCA cases are the [data class admin cases](../integration/data-class-admin-cases.md);
DC-UI the [browser cases](../browser/data-classes-cases.md) (DC-UI-01 to
DC-UI-03) and the [React UI cases](../unit/ui/cases.md) (DC-UI-05 onwards);
PRJ-UI the [Projects browser cases](../browser/projects-cases.md); PCL-LIVE the
[live project-class cases](project-classes-live-cases.md); MC the
[model choice cases](../integration/model-choice-cases.md); RT the
[task routing cases](../integration/task-routing-cases.md); CLI-CLASS the
[signed-in coding cases](../unit/cli-signed-in-coding-cases.md); PR the
[detection routing cases](../integration/personal-data-routing-cases.md); PD the
[detection rule cases](../unit/personal-data-detection-cases.md); and PM the
[detector model cases](../integration/personal-data-model-cases.md).
`tests/unit/test_data_class_scenario_map.py` fails if a scenario is missing here
or a case named here has no row in its own catalog or no test.

| Story | Scenario | Checked by |
| --- | --- | --- |
| ST18 | Off by default | DCA-01, CLASS-00, CLASS-10, DC-UI-01, DC-UI-03 |
| ST18 | Starter classes | DCA-02, CLASS-01, CLASS-09, DC-UI-01 |
| ST18 | Add a class | DCA-03, CLASS-02, CLASS-04, DC-UI-11, DC-UI-02 |
| ST18 | Change a class | DCA-04, CLASS-05, CLASS-06, DC-UI-12 |
| ST18 | A class in use | DCA-05, DC-UI-13, PR-10 |
| ST19 | Set a class | DCA-06, PRJ-UI-03, PRJ-UI-05, PCL-LIVE-01 |
| ST19 | Only approved models | MC-07, MC-08, MC-20, RT-04, RT-05, RT-07, PCL-LIVE-02, PCL-LIVE-03 |
| ST19 | The repo can't change it | CLI-CLASS-02, MC-20, PCL-LIVE-04 |
| ST19 | No approved model is up | MC-18, MC-19, CLI-CLASS-01, PCL-LIVE-06 |
| ST19 | No class | MC-21, PCL-LIVE-05 |
| ST20 | Off by default | PR-01, DCA-02, DC-UI-05 |
| ST20 | What detection finds | PD-14, PD-01, PD-05, PM-01, PM-03 |
| ST20 | Code isn't personal data | PD-02, PD-03, PD-04, PM-04 |
| ST20 | Detection holds a request | PR-02, PR-03 |
| ST20 | Detection fails | PR-04, PR-12, PD-06 |
| ST20 | Choose the class | PR-05, PR-11, DC-UI-06 |

The ST20 rows follow the owner's decisions in governance issues #40, #51 and
#56 and keeplane #203: English only, and the five kinds named in the scenario;
a request detection can't read or check within 200 ms is held; a held request
needs a model approved for both the detection class and the project's class
(PR-03); and a class detection uses can't be removed (PR-10).

The CLASS and PCL-LIVE cases need the running Docker preview; the browser cases
(DC-UI-01 to DC-UI-03, PRJ-UI) run against it in CI's preview job, except
DC-UI-01, whose screenshot baselines are macOS-only. PM cases need the optional
detector and run with `-m optional`. The DCA, MC, RT, CLI-CLASS, PR and PD
cases run in every backend pytest run, and DC-UI-05 onwards in the UI unit
tests.
