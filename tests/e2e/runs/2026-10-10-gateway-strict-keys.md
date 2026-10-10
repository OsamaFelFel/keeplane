# 10 October 2026 — isolated gateway key separation

The [plain-English cases](../gateway-policy/strict-key-cases.md), [configuration](../gateway-policy/strict-keys.yaml), [runner](../gateway-policy/verify_strict_keys.py) and [JSON result](2026-10-10-gateway-strict-keys.json) are versioned. The runner launched a disposable instance of the same pinned agentgateway image used by the previews on the existing local Docker network. It generated two fresh keys in memory and removed the instance after the checks.

| Case | Observed | Verdict |
| --- | --- | --- |
| GW-KEY-01 | Sibling model list 401, management 401, direct chat 401, invalid bearer plus forged headers 401; upstream calls added 0 | Pass |
| GW-KEY-02 | Runtime key model list 200 and chat 200; management 401 | Pass |
| GW-KEY-03 | Admin key management 200; chat 401 | Pass |

The gateway's strict runtime API-key policy and `ui.policies.apiKey` closed the paths that the unprotected preview had exposed. This is an isolated single-instance result. The runtime key was not scoped to a project or data class, the management API still shared the same network port, and Kubernetes network policy was not tested. The current live previews still use the unprotected configuration until their key plumbing and regression are completed. The image's customer-install license gate remains open. **This result does not approve a release gateway.**
