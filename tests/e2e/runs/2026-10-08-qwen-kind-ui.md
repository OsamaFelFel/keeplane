# 2026-10-08 real Qwen in the local Kubernetes preview

The first Kubernetes preview offered Qwen in Add model while it had no Qwen
runner. Registration returned “The local Qwen runner is not ready.” We deployed
the pinned llama.cpp runner and Qwen2.5 Coder 0.5B GGUF model in the isolated
kind cluster. The runner reached Kubernetes Ready state.

The first API registration succeeded but an immediate prompt returned HTTP
404 while a gateway replica loaded the new model. Keeplane now retries only
`model_not_found` responses from that short registration window. The first
browser registration then showed a stale list; the page now checks briefly
until the new model appears.

| Case | Observed result | Evidence |
| --- | --- | --- |
| LOCAL-07 and LOCAL-09 on Kubernetes port 13000 | `local-qwen` registered and returned generated Python code; its source and upstream ID were correct | [JSON](2026-10-08-kind-qwen.json) |
| LOCAL-07 and LOCAL-09 on Docker port 3000 | The existing real Qwen route still answered | [JSON](2026-10-08-docker-qwen-recheck.json) |
| LOCAL-17 in the browser | Add model offered only Qwen Coder and the fixed answer fixture. Previously registered guarded trial entries were absent from the Docker model list and selector. | Browser inspection on both local URLs |
| LOCAL-18 in the Kubernetes browser | Added `ui-qwen-verified`; it appeared immediately and was selected. A coding prompt returned a generated `add_integers` Python function. | Browser inspection at port 13000 |
| Local model regression on both installs | Seven checks passed on each | [Kind JSON](2026-10-08-kind-after-qwen.json), [Docker JSON](2026-10-08-docker-after-qwen.json) |
| Gateway replica failure regression | Five checks passed, including ten new calls after removing a pod | [JSON](2026-10-08-kind-failover-after-qwen.json) |
| Guarded credential-forwarding transport test | Four checks passed through the test-only API path | [JSON](2026-10-08-guarded-after-ui.json) |

The guarded endpoint is a disposable credential-forwarding fixture backed by
the same Qwen runner. It is not a separate model offered to users. The real
Qwen runner remains a small local preview model, not a quality benchmark for
production coding work.
