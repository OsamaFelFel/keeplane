# Run the local Keeplane regression

**Edition:** Open Source

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
order. The JSON result lists every suite, case verdict, duration, exit code,
Git commit, and stack-lock checksum. It rejects a suite that silently omits
an expected case. The command exits nonzero when any suite fails.

The run writes individual suite reports to a temporary directory and leaves
older versioned evidence alone. Review the new JSON and commit it with the
component change when it is meaningful evidence. The local tests include
fixed-answer mocks and a real Qwen runner; they do not test external model
subscriptions or certify a release gateway.
