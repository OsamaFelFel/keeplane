# Project records

Projects keep their name and the accounts that have used them, even before
onboarding. Recording use does not grant access or assign a data class.

Sign in as an admin and open **Projects**. Search by project name, then use
Previous and Next to move through the list. Each row shows whether the project
is initialised and who used it. The data-class column is hidden while classes
are off. On a narrow screen, scroll the table sideways inside its frame.

For integration checks, a signed-in admin can read `/api/projects` on the
Keeplane application. Use `search`, `page` and `page_size` to narrow the result;
pages contain 25 projects by default and at most 50. Developers cannot read
this organization-wide list. Class fields appear only while classes are on.

An admin integration can set a registered project's class with
`PUT /api/projects/{id}/class`, using `{"class_id":"confidential"}` or
`{"class_id":null}` for none. It requires the same CSRF token and action header
as other admin changes. Turn on data classes first. A class in use cannot be
removed; clear or change the project's assignment first. Settings Audit records
real assignment changes when that record kind is enabled.

The current records come from the server's project-use service. CLI first-use
registration and the class dialog are separate delivery steps. No onboarding
completion is recorded yet.
