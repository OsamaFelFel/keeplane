# 10 October 2026 — gateway key separation in the local previews

The [baseline direct-bypass result](2026-10-10-gateway-bypass-diagnostic.json) had unauthenticated model listing, management read and two upstream calls from each internal sibling workload. The [isolated strict-key trial](2026-10-10-gateway-strict-keys.md) then proved runtime/admin key separation on the exact pinned image. The [staged Docker recheck](2026-10-10-docker-strict-bypass.json) and [Docker plus kind recheck](2026-10-10-protected-gateway-bypass.json) used the same [plain-English bypass cases](../gateway-bypass-cases.md).

| Path after rollout | Anonymous list | Anonymous management | Direct chat | Invalid bearer and forged headers | Fixture calls added |
| --- | ---: | ---: | ---: | ---: | ---: |
| Docker managed gateway | 401 | 401 | 401 | 401 | 0 |
| Kind managed gateway | 401 | 401 | 401 | 401 | 0 |
| Kind supplied gateway stand-in | 401 | 401 | 401 | 401 | 0 |

The public Keeplane model list, management-shaped path and chat route also returned 401 without a session on Docker and kind. The app uses a runtime key for model traffic and a separate admin key for gateway configuration. Raw keys are in local private files or Kubernetes Secrets; the gateway configuration receives only SHA-256 key hashes. Re-running local setup preserves the generated keys. The existing-gateway preflight now receives both credentials and still rejects a wrong version or absent model.

The [full regression](2026-10-10-gateway-keys-regression.json) passed **33 of 33 suites and 174 case records** across Docker and kind, including protected accounts, data classes, Audit, model registration and replacement, Qwen transport, gateway replica failure, existing-gateway preflight, provider-key rotation and the integrated demo. The chart linted and rendered in managed and existing modes before deployment.

This closes the tested **credential-free direct path in the local previews**. It does not establish project-bound execution, class enforcement at the final gateway destination, alternate API protection, management network isolation, a release-approved image, or a production Helm package. The kind cluster has no tested enforcing NetworkPolicy. The app-only `keeplane-existing` fixture remains an internal unprotected account trial. Agentgateway remains a transport and policy integration candidate, not the selected release gateway.
