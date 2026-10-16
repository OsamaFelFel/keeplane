# Bind decisions to the serving gateway

Run `python -m pytest tests/unit/test_applied_gateway.py tests/integration/test_installed_runtime.py`.
The reader uses a real disposable HTTP server; callback tests use a synthetic
management/applied-state reader. No shared gateway is changed.

| Case | Expected result |
| --- | --- |
| Either callback sees changed, absent or unavailable applied state | Deny. |
| Raw model lacks an explicit stable ID | Deny enrollment even with a matching fresh approval. |
| Private runtime credential is replaced | The next read uses the new server-held value. |
| Redirect, non-200 response, wrong content type, malformed/duplicate JSON or body over 1 MiB | Fail closed; do not redirect or retry. |
| Bad URL or absent, relative, malformed or oversized private secret | Refuse before contact. |
| Native request latency, pending/total counts, health or consecutive failures change | Keep the same signature only at the exact active endpoint-info path. Health must be finite and between 0 and 1; failures must be an unsigned 64-bit integer. |
| Health/failure measurements are missing or malformed | Deny. |
| Provider address, capacity, policies, creation time or unknown fields change | Change the signature. |
| Active/rejected membership, eviction deadline or ejection count changes | Change the signature. |
| A policy/config field happens to use a measurement name | Keep it in the signature. |
| An existing manifest uses the previous signature calculation | Deny until explicit fresh enrollment. No compatibility fallback. |

Pinned source revision `ea5608642b9d5c94c5baf5fd9f2f9849b808e963` defines these
five measurements in `types/loadbalancer.rs:1006`; `start_request` increments
counts and `finish_request` records latency, health and failures. Default 5xx or
connection failures update health even without eviction (`telemetry/log.rs:843`).
The supported single-provider group has no default eviction (`llm/mod.rs:78`).
Eviction configuration and state stay bound. This is the only normalization.
`proxy/httpproxy.rs:1050` retains a router across awaited entry policies, then
`make_backend_call` resolves the concrete backend and its policies through fresh
store reads. `store/binds.rs:2245` updates the local store under one write lock.
These facts do not establish a request-long snapshot or lease.

This prerequisite supplies the private read contract and current-state gate.
It does not install or enable an endpoint. Native compiled routing, field
stability and provider-contact controls remain required before installation.
