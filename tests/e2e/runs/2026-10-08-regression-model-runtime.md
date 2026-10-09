# 2026-10-08 regression after the model runtime test change

The local Docker preview and the isolated kind trial stayed running. This
change added an executable model-runtime case and corrected the operational
guide; it did not change the Keeplane app, gateway configuration, or images.

| Run | Result | Evidence |
| --- | --- | --- |
| Docker model registration and transport | 7 passed | [JSON](2026-10-08-regression-docker.json) |
| kind model registration and transport | 7 passed | [JSON](2026-10-08-regression-kind.json) |
| Real Qwen route on Docker | 2 passed | [JSON](2026-10-08-regression-qwen-docker.json) |
| Real Qwen route on kind | 2 passed | [JSON](2026-10-08-regression-qwen-kind.json) |
| Guarded endpoint transport on Docker | 4 passed | [JSON](2026-10-08-regression-guarded-docker.json) |
| kind gateway replica failure and existing-gateway mode | 5 passed | [JSON](2026-10-08-regression-kind-failover.json) |
| Model runtime settings and output limit on Docker | 2 passed | [JSON](2026-10-08-model-runtime-docker.json) |
| Model runtime settings and output limit on kind | 2 passed | [JSON](2026-10-08-model-runtime-kind.json) |

All 31 automated checks passed. The browser-only design measurements were not
rerun because this change did not alter the UI; their previous evidence is in
[the real Qwen browser run](2026-10-08-qwen-kind-ui.md). These runs do not
verify production storage, external provider subscriptions, restricted egress,
or a customer-owned gateway.
