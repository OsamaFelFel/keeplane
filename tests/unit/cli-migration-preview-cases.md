# CLI migration preview

- **CLI-MIG-01:** Inventory Claude, Codex and Qwen sources, preserve hashes and
  directory scope, and flag conflicting instructions and unsupported fields.
- **CLI-MIG-02:** Leave source contents and modes unchanged, never open credential
  or session stores, and print no instruction or settings values.
- **CLI-MIG-03:** Refuse symlink files/directories and skip nested repositories;
  do not read their contents.
- **CLI-MIG-04:** Keep valid inventory when settings are malformed and block
  oversized files. Require an explicit Git repository root.

Run `python -m pytest tests/unit/test_cli_migration_preview.py`.
