# Preview an existing CLI setup

This experimental, read-only command inventories a Git repository before a
later onboarding step. It does not migrate files or select a coding runtime.
Use Python 3.11+ on macOS or Linux; no model, account or network is needed.

```mermaid
flowchart LR
  Sources[Existing project files] --> Preview[Read-only inventory]
  Preview --> Review[Migration findings for review]
```

With the [CLI installed](cli-install.md), run from your project:

```sh
keeplane init --preview
```

Or choose the root explicitly with `--directory /absolute/path/to/project`.
`--preview` is required; omitting it does not start onboarding. No account or
server connection is needed. From the Keeplane source tree, the same command is:

```sh
python3 components/cli/keeplane.py init --preview --directory /absolute/path/to/project
```

The original standalone entry point remains available:

```sh
python3 components/cli/migration_preview.py /absolute/path/to/project
```

The JSON output lists source paths and hashes, instruction targets to review,
conflicting guidance, recognized setting names and unknown fields. Different
instruction files in the same directory are flagged before suggesting that a
later migration preserve their content in `AGENTS.md`; nested guidance keeps
its directory scope. No content or setting values are printed.

Recognized sources are `AGENTS.md`, `CLAUDE.md`, `QWEN.md`, Claude project
`settings.json` and `settings.local.json`, Codex project `config.toml`, Qwen
project `settings.json`, and `.mcp.json`. The setting categories are an initial
review list, not a complete vendor schema or a compatibility guarantee.

Hooks, credential helpers and MCP configuration are flagged for review; nothing
is executed or imported. Credential files, session histories and user-home
profiles are not opened. Symlinks, nested repositories, Git internals, dependency
trees and build output are skipped. Each source is limited to 1 MiB.

Exit 0 means discovery completed, even if conflicts need review. Exit 1 means a
source is unreadable or malformed; valid inventory is still shown. Exit 2 means
the selected root cannot be scanned. Fix blocked sources and rerun. There is no
apply command, and all existing files remain untouched. Other CLI commands still
support Python 3.9+; this preview reports its Python 3.11 prerequisite when needed.
