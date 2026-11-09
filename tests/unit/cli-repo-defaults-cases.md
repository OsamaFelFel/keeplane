# `keeplane code` in any repo with no options

Spec 009 ST30 (D149, ADR 030). Journey: DEV-02, DEV-03. Synthetic server and
runtime doubles; run `python -m pytest tests/unit/test_cli_repo_defaults.py`.

| Case | Expected result |
| --- | --- |
| REPO-01 Default profile | Every command uses `~/.config/keeplane/account` (or `$XDG_CONFIG_HOME/keeplane/account`); `login` makes its private 0700 folder. `--profile` still overrides. |
| REPO-02 Only the task | In a clone, `keeplane code "task"` with a gateway address in the profile registers the repo's project with its remote path as name, lists its models, asks the server's `task-model` route, names the chosen model on stderr ("Run `keeplane use MODEL` to choose another."), and runs `opencode` from `PATH` against that gateway with the project header. |
| REPO-03 Old flags | `--profile`, `--project`, `--name`, `--model`, `--runtime` and `--gateway` still override every default; with `--model` the server's pick isn't asked. |
| REPO-04 No gateway yet | Until the server gives a gateway address at sign-in (task 009-02), `code` without `--gateway` says "Keeplane doesn't know your gateway address yet, so nothing was sent…" and makes no request. `--gateway` alone is then enough. |
| REPO-05 Bad saved gateway | A saved address that isn't HTTPS (or loopback HTTP) ending in `/v1` is refused before any request. |
| REPO-06 Finding the runtime | `--runtime`, then `"runtime"` in the settings file, then `opencode` on `PATH`. |
| REPO-07 No runtime | With none found, `code` says how to install OpenCode V2 2.0.27 and sends nothing. |
| REPO-08 Wrong version | A runtime reporting another version, or a missing file, is named in the message and not run. |
| REPO-09 No usable pick | When the server picks no model, picks one outside the catalog, or is too old to pick (404), `code` stops before the runtime; a 503 says Keeplane is unavailable. |
| REPO-10 Other commands | `models`, `register-project` and `keys list` use the repo's project; `--project` overrides. |
| REPO-11 Not a repo | Outside a Git repo, `code`, `models` and `register-project` send nothing and name `--project` and `--name`. |
