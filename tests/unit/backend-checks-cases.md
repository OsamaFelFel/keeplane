# Backend check sharding and test password hashing

Run `.venv/bin/python -m pytest tests/unit/test_backend_checks.py`. The CI
`backend-tests` job runs the unit and integration checks in parallel shards
defined in `tests/support/shards.py`; the `backend` job runs the Python source
check and passes only when every shard passed. Run one shard locally with
`pytest tests/unit tests/integration --shard <name>`; without `--shard`,
`pytest` still runs everything in one process.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| BC-01 | List every `test_*.py` file under `tests/unit` and `tests/integration`. | Each one belongs to exactly one shard. |
| BC-02 | Look at each folder's shard ranges. | They follow on from each other with no gap or overlap, from the first possible file name to no upper bound, so a new or renamed file always lands in a shard. |
| BC-03 | Check every shard. | Each one has at least one test file, so no shard job runs empty. |
| BC-04 | Compare the CI matrix with the shard list. | `checks.yml` lists exactly the shard names, in the same order. |
| BC-05 | Collect a file with a shard that does not own it, or a file outside the sharded folders. | The first collects nothing; the second stops with a usage error instead of silently running nothing. |
| BC-06 | Hash a password under the test settings and check it with the application's PBKDF2 hasher, and the other way round. | Both pass: tests keep the application's stored algorithm and format and only use fewer rounds. The application settings list only Django's PBKDF2 hasher: the earlier preview's import hasher is gone with the import (ADR 014). |
