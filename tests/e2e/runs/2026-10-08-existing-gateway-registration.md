# Existing gateway registration in local kind

**Date:** 8 October 2026  
**Profile:** `kind-keeplane`, isolated kubeconfig at
`/private/tmp/keeplane-kind-kubeconfig`  
**Candidate:** agentgateway standalone chart v1.6.0, integration trial only

The supplied gateway ran independently in `supplied-gateway` with its own
PostgreSQL fixture. Keeplane ran in `keeplane-existing` with
`gateway.mode=existing`, `gateway.install=false`, and
`gateway.url=http://supplied-gateway.supplied-gateway.svc.cluster.local:4000`.
The managed Keeplane installation remained in `keeplane`.
The complete `deploy/local/kind-up.sh` setup was rerun successfully after the
registration test. All managed and supplied gateway, app, model and PostgreSQL
Deployments were Ready afterward.

## Cases and observations

Command: `python3 tests/e2e/test_kind.py`. The suite was repeated after the
complete setup rerun to include the new K8S-07 case; all seven cases passed.

| Case | Result | Observation |
| --- | --- | --- |
| K8S-01 | Pass | Managed gateway had two ready replicas. |
| K8S-02 | Pass | Both replicas listed `second-local`. |
| K8S-03 | Pass | Ten new fixture calls succeeded after one gateway pod was deleted. |
| K8S-04 | Pass | The managed gateway recovered to two ready replicas. |
| K8S-05 | Pass | App-only namespace contained only Keeplane's Deployment and Service. Keeplane registered `customer-managed` into the supplied gateway and received `mock answer`. |
| K8S-06 | Pass | Supplied catalog contained its prior `customer-fixture` plus `customer-managed`; neither appeared in the managed catalog. Managed `second-local` did not appear in the supplied catalog. |
| K8S-07 | Pass on added regression | Five immediate repeat registrations after pod recovery each returned HTTP 200 with `existing: true`. |

`python3 tests/e2e/test_stack_lock.py` passed LOCK-01–04. Both gateway
installations used the pinned image digest and chart v1.6.0; both reported
runtime v1.6.0. `KEEPLANE_BASE_URL=http://127.0.0.1:13000 python3
tests/e2e/test_qwen.py` passed LOCAL-07 and LOCAL-09 through the real local
Qwen runner.

The first `test_local.py` run immediately after K8S-03 passed six cases but
LOCAL-11 saw HTTP 500 on repeat registration of `second-local`. The same
request returned HTTP 200 on direct retry. A full second `test_local.py` run
passed all seven cases. The added K8S-07 regression did not reproduce the
error in its first run. The single observed HTTP 500 still needs a readiness
investigation before a release gateway decision.

A later managed kind rerun reproduced this behavior: the gateway logged an
HTTP 500 for `GET /api/config/resources/llm.model` after 30,005 ms, while
inference calls still returned HTTP 200. The next model-configuration read
succeeded. Keeplane now retries this read up to three times and never retries
the write; the gateway's 30-second stall remains a candidate release risk.

The app-only final run observed a longer failure in the supplied gateway:
after registering `mock-local`, a subsequent model-configuration read blocked
on `SELECT ... FROM agw_config_resources` for **120.030 seconds** according to
the gateway's slow-query log. The app's client had already timed out at 90
seconds. A later read completed in 18 ms. This is a failed trial observation,
even if a settled rerun passes; the root cause and behavior under load need
to be understood before selecting this gateway for release.
The preview now limits each model-configuration read to ten seconds and makes
at most three read attempts. This bounds the UI wait; it does not resolve the
gateway's database or pool stall.
During the final app-only pass, a model-configuration read again lasted ten
seconds; Keeplane retried and all four app-only runner cases passed. The
failure is intermittent, and this passing run does not clear it.

## Limits

This is a separate upstream installation in the same kind cluster, not a
customer's production gateway. It does not prove version preflight, TLS,
authentication, model ownership tracking, policy gating, durable PostgreSQL,
node failure or an external provider. Existing-gateway mode is proven for
this pinned local trial only.
