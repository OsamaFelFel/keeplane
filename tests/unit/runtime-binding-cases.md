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
| Only validated request measurements change | Keep A's binding. Eviction and unknown fields remain bound. |
| Reading the snapshot | Leave the input unchanged; return no key or definition. |

Pinned source `ea5608642b9d5c94c5baf5fd9f2f9849b808e963` selects virtual aliases
first, then matches concrete model names and headers (`llm/model_router.rs:347,
526–541,709`). Explicit IDs produce stable backend names (`types/local.rs:4480`).
Backend and policy dump collections are sorted by their store keys
(`store/binds.rs:2185–2198`). This reader excludes only disjoint exact model
targets; shared routes, listeners, configuration and every selected-target field
stay bound. It makes no lease, loaded-key or in-flight revocation claim.

Native add/edit/remove and tamper controls remain required before connecting
this reader to automatic publication or the installed gate. Legacy routing,
compatible customer gateways and safe activation on every copy remain required
integration work, rather than behavior implemented by this reader.
