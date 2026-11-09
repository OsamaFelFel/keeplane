# CLI settings file

ADR 030. One file outside every repo holds the developer's CLI settings. Run
`python -m pytest tests/unit/test_cli_settings_file.py`.

| Case | Expected result |
| --- | --- |
| SET-01 Where | `$XDG_CONFIG_HOME/keeplane/settings.json` when that is an absolute path, otherwise `~/.config/keeplane/settings.json`. |
| SET-02 No file | No file means no settings; nothing is created by reading. |
| SET-03 Saving | `runtime`, a project's `model` under `projects`, and a model's request settings under `models` are saved and cleared through helpers. The file is 0600 in a 0700 folder, written atomically under a lock, and keys the CLI doesn't know are kept. |
| SET-04 Unknown keys | Unknown keys at any level are ignored, never refused. `~` in `runtime` is expanded. |
| SET-05 Wrong shapes | Invalid JSON, duplicate keys, a non-object file, a relative or non-text `runtime`, and `projects` or `models` sections of the wrong shape are refused with the file's path. |
| SET-06 Others can't change it | A file that a group or others can write, or a link, is refused, because `runtime` names a program the CLI runs. |
| SET-07 Bad values | A bad project ID, model ID, settings value or relative runtime path is refused before anything is written. |
