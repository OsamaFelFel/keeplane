# 2026-10-08 separate supplied gateway trial

The isolated kind cluster now has two independent agentgateway installations.
The managed Keeplane release has two replicas and PostgreSQL-backed model
registration in `keeplane`. A separate upstream standalone chart in
`supplied-gateway` has one replica and a static `customer-fixture` model.
The app-only Keeplane release in `keeplane-existing` points to that separate
gateway and installs no gateway of its own.

| Run | Result | Evidence |
| --- | --- | --- |
| Managed kind model registration and transport | 7 passed | [JSON](2026-10-08-supplied-gateway-local.json) |
| kind replica failure, recovery, app-only mode and separate catalogs | 6 passed | [JSON](2026-10-08-supplied-gateway-kind.json) |
| Docker model registration and transport | 7 passed | [JSON](2026-10-08-supplied-gateway-docker.json) |
| Docker guarded endpoint transport | 4 passed | [JSON](2026-10-08-supplied-gateway-guarded.json) |
| Real Qwen route on Docker and kind | 2 passed each | [Docker](2026-10-08-supplied-gateway-qwen-docker.json), [kind](2026-10-08-supplied-gateway-qwen-kind.json) |
| Qwen context and output-limit regression on Docker and kind | 2 passed each | [Docker](2026-10-08-supplied-gateway-runtime-docker.json), [kind](2026-10-08-supplied-gateway-runtime-kind.json) |
| Pinned component lock against running Docker, kind and Helm | 4 passed | [JSON](2026-10-08-stack-lock.json) |

All 36 automated checks passed. `customer-fixture` answered through the
app-only install. Its model was absent from the managed gateway, while
`second-local` was present only in the managed gateway. Browser-only design
measurements were not rerun because no UI code changed.

This is a stand-in for a customer-run gateway: the separate upstream chart is
still in our kind cluster and uses a static fixture. It does not verify an
actual customer deployment, external HTTPS, production identity, or a
customer's model-registration flow.
