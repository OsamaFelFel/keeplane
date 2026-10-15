# React Models stage, 10 October 2026

## What is ready

The protected Models and routing page is now in the React admin shell at
`/app/models` in the Docker, managed kind, and customer-run gateway previews.
It lists managed and outside-gateway models, discovers a local runner, shows
its active context, and provides Add, Set up, Edit, and Remove actions through
the existing model API. The [local model guide](../../../docs/guide/model-add-local.md)
describes how to try it. Complexity and persona routing controls are not yet
implemented.

## Cases and results

- The [plain-English browser cases](../../browser/models-cases.md) cover the
  table and 320px layout, local runner Add, unsupported shared-key error, and
  removing an outside model's Keeplane setup. All four passed as part of the
  full browser runs, which passed 19/19 each on
  [Docker](../../browser/runs/2026-10-10-react-models-all-docker.json),
  [managed kind](../../browser/runs/2026-10-10-react-models-all-kind.json), and
  [customer-run gateway kind](../../browser/runs/2026-10-10-react-models-all-existing.json).
- The [full local regression](2026-10-10-react-models-regression.json)
  completed with 47/48 suites and 286 recorded cases. Preview parity, protected
  account, Data Classes, Audit, model management, cloud key rotation, and the
  managed kind Qwen runtime cases passed. The run restored the original Data
  Classes mode.
- The only failing suite was `docker-runtime` (`LOCAL-19`, `LOCAL-20`): its
  long direct request to Docker's Qwen runner produced no JSON after the
  120-second HTTP timeout. A single focused retry reproduced a `TimeoutError`
  at the **direct runner** request, before any gateway request. The Docker Qwen
  container remained healthy; its log recorded cancellation at the timeout.
  These two runtime cases remain unverified on Docker. Managed kind passed
  both. This failure is retained rather than counted as a pass.
- `npm run build`, `npm run lint`, and `git diff --check` passed. Lint reported
  warnings, including one data-loading warning in the new page; it reported no
  errors.

The browser tests use controlled API responses to check rendering and actions;
the local end-to-end suites exercise real APIs and gateways. Neither the
customer-run shared-key delivery path nor project-class bypass resistance is
established by this stage.
