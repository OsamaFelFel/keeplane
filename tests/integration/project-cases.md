# Project use

- First use by an active account creates a project and records who used it,
  without onboarding or assigning a data class.
- Repeated use keeps the same project, name and first-use times; last-use times advance.
- A request waiting behind another user's registration cannot move last use
  before the project's first use.
- Two accounts can use one project without replacing each other's usage.
- Missing, unknown or disabled accounts cannot create project records.
- Invalid IDs and blank, oversized or control-character names create nothing.
- If writing usage fails, the project registration rolls back too.

## Admin listing

- A signed-in admin can search project names and page through results in a
  stable order. Repeated use shows one account once, without private account fields.
- A developer or anonymous caller cannot read the organization's project usage.
- Class names reflect current definitions. Class fields disappear while classes
  are off; stored assignments remain intact.
- Invalid or oversized page/search requests fail clearly. Storage failure gives
  an unavailable response without exposing database details.

## Class assignment

- Only an admin can choose an existing class or explicitly choose none for a
  registered project. Browser writes require CSRF and the normal action header.
- Classes must be on. Switching them off preserves earlier assignments and
  rejects new changes until they are enabled again.
- A class used by a project cannot be removed. Clearing the assignment releases it.
- Settings Audit records each real change once when enabled. If Audit cannot
  save a required record, the class change rolls back too.

## Class enforcement (Spec 005 ST19)

| Scenario | Where it is checked |
| --- | --- |
| Set a class | The cases above and browser case PRJ-UI-03 in `tests/browser/projects.spec.ts`. |
| Only approved models, whatever the routing picks | [Model policy](model-policy-cases.md); gateway entry and selected-model checks in `test_installed_runtime.py`; fallback choice MC-07/MC-08/MC-17; native fallback (live) in [native fallback cases](native-runtime-fallback-cases.md); admins get no bypass ([runtime callback](runtime-callback-cases.md)). |
| The repo can't change it | MC-20 and the repository-settings case in [signed-in coding](../unit/cli-signed-in-coding-cases.md). |
| No approved model is up | MC-06, MC-18 and MC-19; the CLI stops with a clear message and starts no runtime. |
| No class | [Model policy](model-policy-cases.md) and MC-21. |
