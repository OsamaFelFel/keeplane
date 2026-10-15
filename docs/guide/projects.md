# Project records

Projects keep their name and the accounts that have used them, even before
onboarding. Recording use does not grant access or assign a data class.

For integration checks, a signed-in admin can read `/api/projects` on the
Keeplane application. Use `search`, `page` and `page_size` to narrow the result;
pages contain 25 projects by default and at most 50. Developers cannot read
this organization-wide list. Class fields appear only while classes are on.

The current records come from the server's project-use service. CLI first-use
registration and the Projects screen are separate delivery steps. No onboarding
completion is recorded yet.
