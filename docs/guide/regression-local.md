# Run the local Keeplane regression

**Edition:** Open Source

Pull requests run the frontend build, UI unit tests and lint, plus isolated
account, storage, read-retry and HTTPS CSRF cases in GitHub Actions. Actions are
pinned to commits and use a read-only repository token. These quick checks
complement the running-stack and browser regression below; they do not certify
the Kubernetes gateway or a production release.

The PostgreSQL job also builds the real API/UI and runs the [two-copy account
fixture](../../tests/e2e/postgres-accounts-cases.md), including shared throttling,
atomic Audit failure, database/app restart, fresh-database restore and password
rotation. Its gateway is a test API fixture; the running-stack suites still
cover the supported trial gateway separately.

Keep the single protected Docker preview and isolated kind cluster running.
The [local model](local-preview.md), [account](accounts-local.md), and
[Kubernetes](kubernetes-local.md) guides show how to start each. The Docker
startup command loads the real Qwen model before the run.

From the Open Source repository root:

```sh
python3 tests/e2e/run_regression.py \
  --output tests/e2e/runs/YYYY-MM-DD-full-regression.json
```

Replace the filename with a new date and run label. The runner checks the
isolated kind context and both preview health endpoints first. It then runs
the [plain-English regression set](../../tests/e2e/regression-cases.md) in
order, including the protected customer-run gateway app through a temporary
loopback port-forward. The JSON result lists every suite, case verdict, duration, exit code,
Git commit, and stack-lock checksum. It rejects a suite that silently omits
an expected case. The command exits nonzero when any suite fails.

The run writes individual suite reports to a temporary directory and leaves
older versioned evidence alone. Review the new JSON and commit it with the
component change when it is meaningful evidence. The local tests include
fixed-answer mocks and a real Qwen runner; they do not test external model
subscriptions or certify a release gateway.

For a React UI change, also run `npm run build`, `npm run lint` and
`npm run test:unit` from `components/admin-ui/web/`, then run `npm test` from
`tests/browser/` for Docker and `KEEPLANE_BASE_URL=http://127.0.0.1:13000 npm test`
for kind while both previews are running. The browser suite's
[plain-English cases](../../tests/browser/users-cases.md) and checked-in
1280px and 320px screenshots cover visual and keyboard behavior that HTTP
tests cannot see. Install its headless browser with
`npx playwright install chromium --only-shell` on a new workstation.
