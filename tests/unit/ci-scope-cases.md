# CI documentation selection

| Change or failure | Expected application checks |
| --- | --- |
| Only added or modified regular Markdown in README.md, components/cli/README.md or docs/ | Skip the four application jobs; keep their check names. |
| Code, tests, licences, workflows, unknown paths or mixed changes | Run all four. |
| Deleted, renamed, executable or symlink documentation | Run all four. |
| Empty diff, missing Git base, invalid SHA or unreadable/malformed event | Run all four. |
| Main push, initial push or manual run | Run all four. |
| Quoted/newline filenames | Read NUL-separated paths; never execute filename text. |
| Classifier job fails or has no affirmative output | Run all four unless the workflow is cancelled. |

The existing build, test, cleanup and reporting steps are unchanged. Selection
uses the committed PR base/head diff and imports no third-party path action.
