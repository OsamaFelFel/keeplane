# 10 October 2026 — current gateway bypass diagnostic

The [plain-English cases](../gateway-bypass-cases.md), [probe](../test_gateway_bypass_probe.py), [worker](../gateway_bypass_worker.py), and [machine result](2026-10-10-gateway-bypass-diagnostic.json) are versioned together. The probe used the image pinned in `deploy/local/stack.lock.json` and the running protected Docker and kind previews. The sibling Docker container and two kind pods carried no Keeplane credentials or Kubernetes service-account token. The probe removed both pods after the run.

| Path | Unauthenticated model list | Unauthenticated management read | Direct chat | Chat with invalid bearer and forged identity headers | Fixture calls added | Release policy |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Docker managed gateway, internal sibling | 200 | 200 | 200 | 200 | 2 | Fail |
| Kind managed gateway, internal pod | 200 | 200 | 200 | 200 | 2 | Fail |
| Kind supplied gateway, internal pod | 200 | 200 | 200 | 200 | 2 | Fail |
| Docker public Keeplane address | 401 | 401 | 401 | Not tested | — | Pass for tested anonymous routes |
| Kind public Keeplane address | 401 | 401 | 401 | Not tested | — | Pass for tested anonymous routes |

The two fixture calls on each internal path prove the unauthorized requests reached the upstream, rather than merely receiving a misleading gateway response. This fails the missing-credential and forged-field parts of governance GW-17, and the internal runtime and management isolation parts of GW-23. A private Service or Compose network only hides the gateway from the host; it does not isolate it from a sibling workload. The public 401s cover only the three tested Keeplane routes.

The current local gateway configuration has no incoming runtime authentication. Earlier isolated agentgateway trials proved strict hashed API keys and per-key model allowlists on a different configuration, but they do not establish project binding, final-destination policy, management isolation, or the release artifact license gate. The next isolated trial must combine strict runtime authentication with a separately protected management path and repeat these probes before any live preview change. GW-18–GW-22 and alternate model APIs remain open. This diagnostic does not select a release gateway.
