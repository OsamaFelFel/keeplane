# 10 October 2026 — protected Docker and kind preview parity

**Edition:** Open Source. **Scope:** local integration trials at ports 3000 and 13000.

Both previews now serve the same built React app and control-plane entrypoints. The managed kind install has the Docker trial's authenticated cloud-provider fixture, so the OpenAI- and Anthropic-shaped model registration and shared-key flows run locally without a paid subscription. Qwen remains the real local model in both previews. The separate customer-supplied gateway fixture is still an app-only trial and is outside this parity claim.

The [plain-English parity cases](../preview-parity-cases.md) and [full regression cases](../regression-cases.md) map to the [final JSON run](2026-10-10-preview-parity-final.json): **47/47 suites, 282/282 case records passed**. It covers sign-in, Users, Data Classes, Audit, local and cloud model management, key rotation, gateway calls, replica failover, Qwen runtime limits and integrated journeys on both addresses. Both original Data Classes modes were restored. After the run, first-admin sign-in and gateway-ready health returned HTTP 200 on each address; both had classes off. All seven managed kind pods were Ready, including two gateway replicas. The kind fixture's mounted provider key matched the original private local key after rotation. No key value is in the evidence.

The [final Docker Chromium run](../../browser/runs/2026-10-10-preview-parity-final-docker.json) and [final kind Chromium run](../../browser/runs/2026-10-10-preview-parity-final-kind.json) each passed **15/15** cases. They cover the React Users, Data Classes and Audit screens, desktop and 320px screenshots, keyboard behavior and quick pagination. UI build, lint and the UI unit test passed; lint emitted existing warnings but no errors. Modified Python test modules compiled.

## Failures found and corrected

- The [baseline](2026-10-10-preview-parity-baseline.json) failed two suites: the chart runner expected obsolete case IDs, and a gateway call raced Kubernetes endpoint removal immediately after a pod stop. The runner now expects the chart's six cases; the failover case waits until the stopped pod is absent from ready endpoints before asserting ten new calls.
- The [first paired full run](2026-10-10-preview-parity-full-regression.json) passed 46/47 suites. Restarting the mock provider during a Secret rotation could close a connection being verified by the gateway. The kind fixture now reads the mounted Secret each request, and the test waits for its update without restarting the pod. The [confirmed pre-UI run](2026-10-10-preview-parity-full-regression-confirmed.json) passed 47/47 suites.
- The first kind browser run exposed an initial search timer returning Audit from page 2 to page 1 after a quick Next click. The same timer pattern existed in Users. Both screens now reset pagination only when the search value actually changes. AU-UI-05 and BR-07 reproduce the quick click. A [post-Audit-fix run](2026-10-10-preview-parity-post-ui-full.json) was deliberately interrupted after 16 passing suites to include the Users fix in one final build; it is partial evidence, not a passing run.

The focused chart, approval and key-rotation checks and their failed attempts are retained in the other `2026-10-10-preview-parity-*.json` files. The final result is the acceptance evidence for this local stage.

## Still open

This does not select agentgateway as the release gateway or prove production packaging. The account store is local SQLite; the customer-supplied gateway mode has not run this protected parity suite. Direct gateway access remains outside the project-class enforcement guarantee, and the D42 trusted-execution conflict remains unresolved. The authenticated cloud-provider fixture verifies protocol and key handling, not a real provider subscription.
