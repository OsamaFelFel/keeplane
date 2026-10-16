# Keep unrelated models independent

Run `python -m pytest tests/unit/test_runtime_binding.py`.

This internal reader returns only model and binding digests. It does not change
the installed gate, publish policy, authorize work or activate new models. Its
caller must supply a trusted expected binding and the correct gateway copy.

| Case | Expected result |
| --- | --- |
| Exact model B is added before A, edited or removed | A keeps its binding, including while B's resource and applied updates differ. |
| A's raw revision, shared entry/private wiring, final guard or stripping changes | A's binding changes. |
| A's provider destination or native authentication differs from its raw definition | Refuse the snapshot. |
| A route can select another backend, or routing uses wildcards, header conditions, virtual models, duplicate IDs or legacy name-only models | Refuse this first reader's unsupported or ambiguous snapshot. |
| A policy has an unknown target or namespace | Refuse; never silently discard it. |
| Retained routes, final callbacks or key exchange reference an excluded model or unknown backend | Refuse. A named host dependency stays bound, including its destination. |
| Native UI management references `/ui` | Retain the exact `internal` UI/empty-namespace/`forward` backend and all management guards; refuse other internal targets. |
| Only validated request measurements change | Keep A's binding. Eviction and unknown fields remain bound. |
| Reading the snapshot | Leave the input unchanged; return no key or definition. |

Pinned source `ea5608642b9d5c94c5baf5fd9f2f9849b808e963` selects virtual aliases
first, then matches concrete model names and headers (`llm/model_router.rs:347,
526–541,709`). Explicit IDs produce stable backend names (`types/local.rs:4480`).
Backend and policy dump collections are sorted by their store keys
(`store/binds.rs:2185–2198`). This reader excludes only disjoint exact model
targets; shared routes, listeners, configuration and every selected-target field
stay bound. Named route and callback references use `backend` in both
`LocalBackend` and `SimpleBackendReference`; bare local names compile to `/name`
(`types/local.rs:1497,5821`, `types/agent.rs:1531–1594`). Retained references must
resolve to retained backends; disjoint model backends cannot secretly become
shared dependencies. The native UI's exact internal forward target is generated
at `types/local.rs:4052–4085` and stays bound. Provider groups must remain the supported single
direct endpoint; virtual-model fallback remains refused. This makes no lease,
loaded-key or in-flight revocation claim.

The disposable native check used the pinned image and a real read-only
Kubernetes ConfigMap projection. It passed all 25 checks: A stayed unchanged
through B's raw definition and final/stripping policy add, edit and removal;
changing A or shared guards invalidated it. The Pod did not restart and no
provider requests were sent. A separate check applied two ConfigMap updates
without restarting the Pod.

Earlier checks are retained privately: an incorrect fixture create endpoint,
the initially unsupported native UI shape, and host-file desired/applied policy
divergence. The host reload cause is unconfirmed; no host hot-reload claim is made.

Automatic publication, the installed gate, legacy routing, compatible customer
gateways and safe activation on every copy still need integration. This reader
alone enables no traffic.
