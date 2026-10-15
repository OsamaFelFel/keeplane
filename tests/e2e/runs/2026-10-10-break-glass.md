# Break-glass sign-in Audit run — 2026-10-10

**Edition:** Open Source local trial. Tested on `feat/react-users-stack` after `f8fb0de`; product baseline `keeplane-governance` `a2a0397`. The final run started at 01:21 UTC with the working tree dirty because this code and report were not yet committed. Stack-lock SHA-256: `0b79e64e66897f37aed2dcc62ce62d75c10f9934dcfa547c8a9f67c4b1d0b5ec`.

## Result

| Check | Outcome |
| --- | --- |
| [Plain-English BG-01–BG-09](../audit-cases.md#always-on-break-glass-sign-ins) | First use, repeat, wrong password, rotation, search, no off switch, secret redaction, and both audit-write and session-write failure directions pass. A failed write returned 503 and committed neither side. |
| [Focused account and Audit run](2026-10-10-break-glass-focused.json) | 6/6 suites, 41/41 cases passed. |
| [Final full regression](2026-10-10-break-glass-full-final.json) | 32/32 suites, 166/166 cases passed across Docker, kind, real Qwen, accounts, models, Audit and the integrated journey. Finished at 01:25 UTC. |
| React browser suite | 6/6 passed after the sign-in backend change. |
| Helm | `helm lint deploy/helm/keeplane` exited 0; the managed, existing-gateway and supplied-gateway local releases rolled out successfully. The new kind app image is 53,093,832 bytes. |
| Running preview | Docker app, gateway, local Qwen and fixtures are up at `127.0.0.1:3000`; kind app, two gateway pods, local Qwen and fixtures are Ready at `127.0.0.1:13000`. |

## Failure and recovery evidence

The [first full attempt](2026-10-10-break-glass-full.json) ended 9/32 after Docker Desktop stopped with low host disk space; most remaining suites could not reach the engine. Docker then restarted with the same volumes. A [focused Qwen recovery run](2026-10-10-break-glass-qwen-recovery.json) found that an unbounded CPU demo response exceeded the gateway's 120-second timeout in Docker, while kind passed. The preview-only `/api/ask` call now asks for at most 64 output tokens. [Docker](2026-10-10-break-glass-qwen-bounded.json) and the [redeployed kind app](2026-10-10-break-glass-kind-redeployed.json) both passed their real-Qwen checks before the final full run.

Unused Docker build cache was cleared without removing images or volumes. A `.dockerignore` now excludes local `node_modules` from the kind app image; its build context transfer fell from about 157 MB to under 5 KB on the incremental rebuild. About 14 GiB of host space remained free at the final check.

This proves the behavior in the local SQLite trial. The production identity store, Kubernetes account deployment and React conversion of the remaining Audit page are still open release work.
