# Test Keeplane

Choose the checks for the behavior you changed. Keep results in ignored
`test-results/` directories and attach them to CI or the PR. Do not commit logs
or generated run reports.

## Automatic pull-request checks

GitHub Actions runs:

- Frontend build, UI unit tests and lint.
- Isolated account/storage tests and the launcher's HTTP/CSRF tests.
- The documented Docker startup command, a custom-port restart, and browser
  behavior checks on Linux. Existing macOS screenshot baselines are checked locally.
- The PostgreSQL package/API fixture, including two-copy accounts, shared login
  limits, atomic Audit, restart, fresh-database restore and password rotation.

Reports are uploaded even when a job fails and retained for 30 days. A passing
job covers its selected checks; these jobs do not certify Kubernetes policies,
real cloud subscriptions or a production release. Release evidence needs longer
retention than routine PR artifacts.

## Frontend and browser checks

In `components/admin-ui/web/`, run:

```sh
npm run build
npm run lint
npm run test:unit
```

With Keeplane running, in `tests/browser/`:

```sh
npm ci
npx playwright install chromium --only-shell
npm test -- --workers=1
```

For another address, set `KEEPLANE_BASE_URL`, for example
`KEEPLANE_BASE_URL=http://127.0.0.1:3080 npm test -- --workers=1`.
Set `KEEPLANE_RUNTIME_DIR` too if you chose a custom credential directory.
Failure traces and screenshot differences go under `test-results/browser/`.
Do not update an expected screenshot until you have reviewed the visible change.

## Complete Docker and Kubernetes regression

Start both the [local application](local-preview.md) and the isolated
[Kubernetes installation](kubernetes-local.md). The full regression currently
expects Docker on port 3000, kind on port 13000, and the isolated kind kubeconfig.
Run from the repository root:

```sh
python3 tests/e2e/run_regression.py --output test-results/full-regression.json
```

Use a new filename per run. Individual suite reports and logs are kept beside
that file in `full-regression-suites/`. The runner checks every expected case ID,
returns a nonzero exit code on failure and restores the original data-class mode.
Use `--suite NAME` for a focused run; it is not a full regression.

The [case catalog](../../tests/e2e/regression-cases.md) lists the selected groups.
The separate [PostgreSQL deployment cases](../../tests/e2e/postgres-deployment-cases.md)
exercise verified TLS, database roles and both gateway modes on the isolated
Calico cluster. Run those explicitly after deployment changes.

## Results and history

A PR summary states the tested commit, commands, pass/fail/unrun results and
artifact links. Preserve failed runs as well as successful ones. Keep test code,
reusable fixtures, case descriptions and deliberate visual baselines in Git.

Earlier generated reports remain available in
[the recorded source revision](https://github.com/OsamaFelFel/keeplane/tree/de0aba5f8052fbbec55a2060309812812f09588e/tests).
Their removal from the current tree does not change the tests or turn a failed
or unrun release gate into a pass.
