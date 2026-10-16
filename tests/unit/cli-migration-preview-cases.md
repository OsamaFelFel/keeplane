# CLI migration preview

- **CLI-MIG-01:** Inventory Claude, Codex and Qwen sources, preserve hashes and
  directory scope, and flag conflicting instructions and unsupported fields.
- **CLI-MIG-02:** Leave source contents and modes unchanged, never open credential
  or session stores, and print no instruction or settings values.
- **CLI-MIG-03:** Refuse symlink files/directories and skip nested repositories;
  do not read their contents.
- **CLI-MIG-04:** Keep valid inventory when settings are malformed and block
  oversized files. Require an explicit Git repository root.
- **CLI-MIG-05:** Unified `init --preview` preserves the standalone JSON and
  exit codes, defaults to the current directory, requires an explicit mode and
  never requests an account or server. Other commands remain usable on Python
  3.9; preview explains its Python 3.11 prerequisite.
- **CLI-MIG-06:** Save a private plan outside Git for one selected root Claude or
  Qwen instruction file; confirmation creates an absent AGENTS.md with identical
  bytes. Original files/modes and Git state stay unchanged. No account, hooks or
  settings are imported; the copied hash works with explicit runtime instructions.
- **CLI-MIG-07:** Refuse conflicting/changed/additional root instructions,
  existing targets, unsafe files, invalid text and tampered/foreign plans.
  Concurrent confirmations cannot replace each other's copy.
- **CLI-MIG-08:** Pre-publication faults clean only random temporary files;
  post-publication faults retain AGENTS.md for review, including human replacements
  or edits. Failed named plans also remain; a fresh plan path supports recovery.
  The installed offline wheel
  executes preview, saved-plan confirmation and instruction-resource lookup.

Run `python -m pytest tests/unit/test_cli_migration_preview.py tests/unit/test_cli_init.py tests/unit/test_cli_migration_apply.py`.
