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
