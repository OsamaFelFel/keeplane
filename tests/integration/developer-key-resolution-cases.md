# Internal provider-key resolution

These isolated Django and filesystem cases use synthetic keys and a synthetic
registry with the real current-definition checker. They make no provider call.

| Case | Check |
| --- | --- |
| Owner isolation | Only the selected owner's active key resolves. Result text is redacted and it cannot be JSON-serialized by default. |
| Replacement/removal | Later reads see the replacement. Removal denies reads even when old-file cleanup is pending; another owner's key remains available. |
| Current binding | Inactive owner, withdrawn approval, changed key choice, changed registry revision, missing stored binding or wrong expected fingerprint denies resolution. |
| Private files | Correctly owned 12/512-byte credentials work with private read-only modes. Symlinked roots/files, trailing-slash symlinks, FIFOs, directories, hard links, public modes, foreign owners and invalid basenames are rejected. |
| Bounded format | Short, oversized, whitespace, control and non-ASCII contents are rejected. |
| Failed commit | A database failure after reading exposes neither the result nor underlying key/path details. |
| Concurrent mutation | A separate SQLite writer attempts replacement/removal while resolution holds the owner decision; it completes only after the read is released. The next read returns the replacement or denies the removed key. |

Run `python -m pytest tests/integration/test_developer_key_resolution.py`.
The concurrency case checks SQLite ordering, not PostgreSQL row-lock behavior.
These cases do not prove native destination binding, cross-replica filesystems,
provider acceptance or revocation of bytes already returned.
