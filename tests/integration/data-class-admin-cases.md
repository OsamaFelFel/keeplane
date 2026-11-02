# Data class admin API cases

**Edition:** Open Source. Spec 005 ST18 and ST19 "Set a class", tasks 005-01
and 005-02. Run `python -m pytest tests/integration/test_data_class_admin.py`
with isolated Django storage. A signed-in admin sends each change with the
admin UI's action header; the gateway's list of set-up models is fixed to
`coder` and `reviewer`.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| DCA-01 | On a new install, read Data classes, Projects and one project's class; try to add a class and to set a project's class. | Data classes are off with no classes; no project row or class read has a class field; both changes are refused until classes are on; no model has a class. |
| DCA-02 | Turn data classes on, then off and on again. | Public, Internal and Confidential are listed in that order, with no model approved for them, and personal-data detection is off with Confidential under Handle it as. Turning on again keeps the same three classes; none is added twice. |
| DCA-03 | Add Restricted with `coder` as its approved model. | Restricted is listed after the starters with `coder` and no projects; `coder` lists Restricted as approved and `reviewer` stays unapproved. |
| DCA-04 | Rename Restricted to Secret and approve `reviewer` instead of `coder`. | Data classes shows Secret with `reviewer`, under the same ID; Restricted is gone, and the models' approvals follow the change. |
| DCA-05 | Set a project to Restricted, try to remove Restricted, then clear the project's class and remove it. | The removal is refused with "Projects still use this class"; Restricted stays, with its model and one project. Once no project uses it, it can be removed. |
| DCA-06 | Set a project's class to Confidential. | The save answers Confidential, Projects shows Confidential for that project and none for another, and reading the project's class back gives Confidential. |

The live Docker preview versions of these are the
[Data classes cases](../e2e/data-classes-cases.md) (CLASS-00 to CLASS-10) and
[PCL-LIVE-01](../e2e/project-classes-live-cases.md); the screens are in
[the browser cases](../browser/data-classes-cases.md) and
[the React UI cases](../unit/ui/cases.md).
