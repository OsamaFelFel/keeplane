# Local account API cases

**Edition:** Open Source. [`test_local_accounts.py`](test_local_accounts.py)
calls the real account API with Django's test client and an isolated database,
so it runs in every `pytest` run without a preview.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| LA-01 | Sign in as the first admin, then sign out. | Identity and Users open; sign-out works only by POST, and afterwards the session is refused. |
| LA-02 | Sign in as a developer and call the admin APIs. | Users, Create user, Change role, Check, Projects and Models all refuse with 403; nothing changes. |
| LA-03 | Open sign-in options without an account and try to create one. | No single sign-on is offered, Create user needs a signed-in admin, and no sign-up route exists. |
| LA-04 | Find the first admin in Users and try to change, remove or copy it. | It is listed as break-glass and managed; role changes and removal are refused; a look-alike name is refused. |
| LA-05 | Rotate the first admin's password and list Users. | One first admin remains, with the same ID and the Admin role. |
| LA-06 | Create an Admin and a Developer. | Each appears in Users with the chosen role and signs in with username and password; no password is returned. |
| LA-07 | Create a user without a role, or with an unknown one. | The API refuses it and creates nothing; the UI supplies Developer by default. |
| LA-08 | Send the same Create user twice, then reuse its operation ID with other details. | One user exists and both answers match; the changed request is refused. |
| LA-09 | Check an operation before and after it creates a user, and as another admin. | Check reports not found, then created with the user; another admin cannot see or reuse it. |
| LA-10 | Create a duplicate name, Check, then retry with a new name and the same operation ID. | The refusal saves nothing, Check finds nothing, and the retry creates the user. |
| LA-11 | Create 31 users, page through 25 at a time and search. | Pages don't repeat users; search is case-insensitive and shows only matches; bad page or search values are refused. |
| LA-12 | Promote a signed-in developer, then demote them. | Users shows each new role; admin access starts at once and demotion ends the session. |

`test_local_identity.py` covers ACCT-17, ACCT-21 and ACCT-22 of the
[account cases](../e2e/accounts-cases.md) at the storage boundary.
