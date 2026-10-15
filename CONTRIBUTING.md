# Contributing

Start with the [local setup guide](docs/guide/local-preview.md). Keep changes
focused on one behavior and explain the problem and resulting behavior in the PR.

## Code and documentation

- Put application code under `components/` and tests under `tests/`.
- Keep readable test cases beside their suites. Add a case when changing a workflow.
- Update the affected user guide and architecture diagram when behavior changes.
- Write instructions for someone using the product: prerequisites, commands,
  expected results, configuration and recovery. Use “Keeplane”; explain edition
  differences only where they affect the reader's task.
- Keep credentials, customer prompts and generated output out of commits.

## Check your change

For frontend changes, run `npm run build`, `npm run lint` and `npm run test:unit`
in `components/admin-ui/`. Run the applicable Python and browser suites too.
The [test guide](docs/guide/regression-local.md) explains running-stack and
Kubernetes coverage and which checks run automatically.

Reports, logs and browser traces belong in ignored `test-results/` directories
or CI artifacts. Keep intentional screenshot baselines and reusable fixtures in
Git. In the PR, state the tested commit, commands, results, unrun checks and artifact
links. Historical reports remain accessible at their original Git commit.

Code is licensed under Apache 2.0. Preserve dependency notices and check the
distribution requirements of every bundled component before shipping it.
