# List my provider keys

Run `python -m pytest tests/integration/test_runtime_key_list.py tests/unit/test_cli_key_list.py`.

| Case | Expected result |
| --- | --- |
| Classes off/on and another project's class | Only the requested project's current allowed models are listed. Stale definitions and models without setup disappear. |
| Personal, shared and no-key choices | Personal reports the owner's saved `added`/`missing` registration; other choices have `own_key_required: false` and `status: null`. |
| Another owner has a key | That registration does not change this owner's status. No identity, key value, filename or fingerprint is returned. |
| Withdraw after initial authentication | The owner-locked authentication recheck refuses before reading key registrations. Cookie-only and invalid credentials fail. |
| Query/body claims or unavailable policy/storage | Refuse with no partial list or underlying error details. |
| Changed CLI account or malformed server response | No list is printed; unknown statuses, extra/duplicate fields, mismatched project, duplicate/unsorted IDs and oversized responses fail. |
| Successful CLI list | Real HTTP GET only, no profile change, no provider/key-file reads, credentials omitted from output. |

`GET /api/runtime/projects/{project_id}/provider-keys` accepts no body/query and
returns `{"project_id":"UUID","models":[{"id":"coder","own_key_required":true,"status":"missing"}]}`.
It reuses current project access/model policy. This read-only snapshot is not a
dispatch permit, provider check or proof of complete ST11 refused-key behavior.
