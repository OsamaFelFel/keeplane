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
| Native per-request latency, pending count or total count changes | Keep the same signature only at its exact endpoint-info path. |
| Provider address, health, capacity, policies, creation time or unknown fields change | Change the signature. |
| A policy/config field happens to use a measurement name | Keep it in the signature. |

Pinned source revision `ea5608642b9d5c94c5baf5fd9f2f9849b808e963` defines these
three measurements in `types/loadbalancer.rs:1006`; `start_request` increments
counts and `finish_request` records latency. This is the only normalization.
`proxy/httpproxy.rs:1050` retains a router across awaited entry policies, then
`make_backend_call` resolves the concrete backend and its policies through fresh
store reads. `store/binds.rs:2245` updates the local store under one write lock.
These facts do not establish a request-long snapshot or lease.

This prerequisite supplies the private read contract and current-state gate.
It does not install or enable an endpoint. Native compiled routing, field
stability and provider-contact controls remain required before installation.
