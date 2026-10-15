# Django model management cutover: local evidence

## Change under test

The protected Add, Set up, runner discovery, shared-key rotation, listing, and
remove APIs now enter Django and DRF through the Keeplane front server. A model
management use case coordinates approval and rollback; the agentgateway adapter
owns registry and chat requests. The former model write handlers were removed
from the front server. The front server still handles the preview Ask request,
Data Classes, and Audit.

## Plain-English cases reused

The documented [local Add](../model-add-cases.md),
[model edit](../model-edit-cases.md),
[model replacement](../model-replacement-cases.md),
[cloud Add](../cloud-add-cases.md),
[key rotation](../key-rotation-cases.md),
[runner](../cases.md), and
[customer-run gateway](../existing-gateway-cases.md) cases exercise the same
public Keeplane routes after the cutover. They check admin protection,
registration, gateway answer verification, approval, duplicate handling,
rollback, key cleanup, and the customer-run gateway restrictions.

## Focused runs

| Preview | Result | Evidence |
| --- | --- | --- |
| Docker | 6 of 6 suites; 37 cases passed | [Docker JSON](2026-10-10-django-model-writes-docker-focused.json) |
| Managed kind and customer-run gateway | 7 of 7 suites; 41 cases passed | [kind JSON](2026-10-10-django-model-writes-kind-focused.json) |

The standalone runner discovery case `LOCAL-25` also passed after extraction
to its adapter. The final full regression result is recorded separately below.

## Full regression on the final preview images

The [full Docker and kind run](2026-10-10-django-model-writes-full-regression.json)
passed all 48 suites and all 290 case records. It covered chart packaging,
image parity, protected UI and account APIs, Data Classes, Audit, model flows,
gateway failover and outage behavior, the customer-run gateway path, Qwen
runtime limits, and the integrated admin journeys. The runner restored the
original Data Classes mode after the run. The managed Docker preview on port
3000 and kind preview on port 13000 remained healthy.

These local fixtures do not prove real cloud subscriptions, production
persistence, or the unresolved project-class bypass guarantee.
