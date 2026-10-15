# Current policy on two gateway copies

This disposable test connects two pinned native gateway paths to real Keeplane
records in one PostgreSQL primary. Both paths use the same developer session,
project class, approval and synthetic shared provider key. Each gateway has its
own private authorizer and mock provider. No real model, shared preview or
customer deployment is changed.
Shared keys are explicit fixture mounts; this does not implement customer
key-delivery APIs.

| Case | Expected result |
| --- | --- |
| Allowed work on either copy | Both answer; the provider receives only the server-selected key. |
| Model changes after entry authorization | Each selected-model check rejects Public; no provider receives the request. |
| Project class changes | Both copies immediately reject a model outside the new class. |
| Model approval is withdrawn | Both copies reject it before provider contact. |
| Shared key disappears | Both copies stop before provider contact, despite native last-known configuration. |
| Session is revoked | Both copies reject the old session. |
| Copy A loses its database link | Its protected listener refuses work; copy B still answers allowed work. |
| Approval is withdrawn while A is disconnected | Neither path reaches a provider. A still rejects the withdrawn model after reconnecting. |
| Copy A loses its authorizer | Its protected listener refuses work; copy B still answers allowed work. |
| Recovery | Restoring A's link or replacing its authorizer restores allowed work at the same protected address. Bounded recovery statuses are retained. |
| Private listeners | A sibling client cannot reach either copy's raw model, management, stats, readiness, authorizer or provider port. |
| Existing gateway configuration | Both copies preserve the unrelated native model and configuration. |

The database and application images must already be cached. Use the existing
PostgreSQL package fixture image, or set `KEEPLANE_RUNTIME_POSTGRES_FIXTURE_IMAGE`
to another tested image containing the PostgreSQL driver. The test resolves it to
an immutable image ID and mounts the checked-out control-plane source read-only.
The gateway, database and Python client images come from `stack.lock.json`.

Run from the repository with its Python test environment:

```sh
python -m pytest tests/integration/test_native_runtime_replicas.py -m live -q
```

Temporary networks, containers and databases are removed even when a check fails.
Generated reports remain outside Git. Connections use an isolated Docker network
without TLS. This does not prove Kubernetes Services, changing endpoint IPs,
streaming, retries, fallback, virtual-model gates, database failover, production
policy publication or a release gateway selection. Authorizer replacement uses a
stable private loopback address inside each gateway's network namespace; it is
not a Kubernetes endpoint-recovery claim.
