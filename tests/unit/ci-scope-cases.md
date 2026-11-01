# CI documentation selection

| Change or failure | Expected application checks |
| --- | --- |
| Only added or modified regular Markdown in README.md, components/cli/README.md or docs/ | Skip the five application jobs, including the component manifest build; keep their check names. |
| Code, tests, licences, workflows, unknown paths or mixed changes | Run all five. |
| A guide whose commands a test checks (`docs/guide/backup-and-restore.md`) | Run all five, so the guide's command checks run. |
| Deleted, renamed, executable or symlink documentation | Run all five. |
| Empty diff, missing Git base, invalid SHA or unreadable/malformed event | Run all five. |
| Main push, initial push or manual run | Run all five. |
| Quoted/newline filenames | Read NUL-separated paths; never execute filename text. |
| Classifier job fails or has no affirmative output | Run all five unless the workflow is cancelled. |

The existing build, test, cleanup and reporting steps are unchanged. Selection
uses the committed PR base/head diff and imports no third-party path action.
