# Django Ask cutover: local evidence

The protected preview Ask request now enters Django. Its small use case checks
the signed-in admin's model approval and the current gateway definition before
asking agentgateway for a model answer. The former Ask handler was removed from
the front server. Gateway transport and the model registry stay in
agentgateway.

The plain-English [model approval cases](../model-approval-cases.md) cover
refusing work before setup, accepting an approved model, and rejecting a
changed model. The [integrated cases](../integrated-demo-cases.md) check a
generated Qwen answer after discovery and approval. The
[customer-run gateway cases](../existing-gateway-cases.md) check that an
unapproved gateway model cannot be used through Keeplane.

| Preview | Focused result | Evidence |
| --- | --- | --- |
| Docker | 2 of 2 suites; 16 cases passed | [Docker JSON](2026-10-10-django-ask-docker-focused.json) |
| Managed kind and customer-run gateway | 3 of 3 suites; 20 cases passed | [kind JSON](2026-10-10-django-ask-kind-focused.json) |

The [full Docker and kind regression](2026-10-10-django-ask-full-regression.json)
passed all 48 suites and all 290 case records. It covered the current chart,
image parity, accounts, Data Classes, Audit, model registration and cleanup,
gateway outage and failover, key rotation, the customer-run gateway, Qwen
runtime limits, and both integrated journeys. The original Data Classes mode
was restored after the run; both managed previews remained ready.

This preview route does not prove project-bound data-class enforcement or
resistance to project impersonation; those remain release-gateway gates.
