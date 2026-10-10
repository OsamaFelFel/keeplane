# Existing-gateway preflight read retry — 2026-10-10

**Scope:** Open Source local Docker and kind integration trial. Source branch: `feat/existing-gateway-preflight`, based on `1cf3869`. The gateway remains a candidate, not a release selection.

The earlier [React Audit full run](2026-10-10-react-audit-full-final.json) found one failed existing-gateway Helm upgrade: the preflight Job reported that the gateway model-management read API was unavailable. The supplied gateway was healthy; its request log showed an 8004 ms management read with no completed HTTP status. The same preflight then passed immediately, followed by a clean 32-suite run. A single slow read should not reject an otherwise compatible gateway installation.

The preflight now retries an unavailable model-list or model-management **read once**. It retries a timeout, HTTP 429, or HTTP 5xx; HTTP 401 and other client refusals still fail immediately. It never retries the inference probe, which may have a cost or side effect. The Helm Job has a 90-second deadline to fit the bounded read attempts. A persistent failure still blocks the installation before Keeplane changes the customer's gateway.

| Check | Observed result |
| --- | --- |
| [Plain-English K8S-14–16](../kubernetes-cases.md) | One simulated unavailable response on each read recovered; persistent HTTP 503 failed after one retry; HTTP 401 failed without retry. All calls were read-only. |
| [Focused run](2026-10-10-existing-preflight-retry-focused.json) | 2/2 suites and 7/7 case records passed, including live K8S-10–13 in kind. The existing-gateway Helm release completed successfully. |
| [Full regression](2026-10-10-existing-preflight-retry-full.json) | 33/33 suites and 172/172 case records passed across Docker, kind, Qwen, account and model flows, Audit, both gateway modes, runtime and the integrated demo. The runner restored the initial data-class mode. |

The Docker and kind previews remain available at `http://127.0.0.1:3000` and `http://127.0.0.1:13000`. This retry improves installation reliability; it does not validate gateway licenses, project policy enforcement, provider compatibility, or release readiness.
