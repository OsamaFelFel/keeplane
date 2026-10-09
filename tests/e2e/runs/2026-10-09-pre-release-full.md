# Open Source pre-release baseline: local verification

**Edition:** Open Source

**Code revision:** `ea853c70500829eb59669162b70a66842f285774` on `fix/oss-edition-boundary`

**Environment:** protected Docker preview and local kind cluster on 9 October 2026

The [current plain-English account cases](../accounts-cases.md) passed **15/15** in the [focused run](2026-10-09-edition-boundary-accounts.json). Admin requests to the former Team API and web paths returned 404. The live navigation had no Team link. The Editions preference showed the line once for an admin, hid it on the second visit, stayed off after a switch change, and reset once when re-enabled. There is no old-trial-data migration case.

The [full regression result](2026-10-09-pre-release-full.json) records a clean worktree at that code revision: **29/29 suites and 150/150 case records passed**. It covered accounts, models, gateway failures, audit, Docker and kind journeys, including a real local Qwen call. No suite failed or was skipped. Reproduce the complete run with:

```sh
python3 tests/e2e/run_regression.py --output /private/tmp/keeplane-regression.json
```

The UI was visually reviewed against Users and Editions in the supplied canvas at the earlier edition-boundary stage. A framework choice and automated browser checks are proposed separately; this result does not claim those checks already exist. The Docker preview remained running after the full run. No customer-installed dependency, image or chart changed in this correction.
