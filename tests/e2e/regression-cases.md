# Full local regression cases

**Edition:** Open Source. Run after a component, policy, gateway integration,
deployment, or model-flow change. The command checks the single protected
Docker preview and the isolated `kind-keeplane` cluster. It
uses the existing test fixtures and the real local Qwen runner. Prepare them
using the [local](../../docs/guide/local-preview.md),
[account](../../docs/guide/accounts-local.md), and
[kind](../../docs/guide/kubernetes-local.md) guides.

```sh
python3 tests/e2e/run_regression.py \
  --output tests/e2e/runs/YYYY-MM-DD-full-regression.json
```

Choose a new filename for each saved run. The runner refuses to overwrite an
existing result. It checks that the isolated Kubernetes context is selected
before any live case, signs in to both protected apps and checks their
gateway-ready JSON rather than accepting a sign-in redirect as health, then
runs the suites in dependency order and checks that each
suite reports its complete expected set of case IDs. It keeps only IDs,
verdicts, failed observations, exit codes, and timing in the result. Individual
trial reports go to a temporary directory, so an ordinary regression does not
rewrite previously committed evidence. A partial result is saved after every
suite if the run is interrupted.

| Group | Plain-English expectation | Case source |
| --- | --- | --- |
| Storage and read retries | Changed model definitions lose approval; data-class and audit constraints hold; gateway read retries are bounded. | [Model approval](model-approval-cases.md), [data classes](data-classes-cases.md), [audit](audit-cases.md), [Kubernetes](kubernetes-cases.md) |
| Locked Docker and kind stacks | Pinned images, chart, model file, and actual runtime versions match the lock. | [Kubernetes](kubernetes-cases.md) |
| Build and protected UI parity | Both running app containers contain the same backend and React build; first-admin sign-in reaches Users, Data Classes, Audit, Models and their APIs on both addresses. | [Preview parity](preview-parity-cases.md) |
| Docker and kind transport | UI, local font, registration, mock answers, Qwen answers, runner discovery, replica failover, and admin UI availability during a gateway outage work. | [Local model](cases.md), [Kubernetes](kubernetes-cases.md) |
| Protected management on both previews | Accounts, Editions, data classes, audit, local and cloud model approval, add, edit, replacement and removal obey the same protected rules in Docker and kind. Cloud-provider keys remain private through registration and rotation. | [Accounts and Editions](accounts-cases.md), [data classes](data-classes-cases.md), [model approval](model-approval-cases.md), [model edit](model-edit-cases.md), [model replacement](model-replacement-cases.md), [model add](model-add-cases.md), [cloud listing](cloud-listing-cases.md), [cloud add](cloud-add-cases.md), [key rotation](key-rotation-cases.md), [model removal](model-removal-cases.md), [audit](audit-cases.md) |
| Protected customer-run gateway path | The separately installed gateway keeps its unrelated model while Keeplane's own app requires sign-in, completes the 21 account cases, sets up one model and refuses an unapproved one. | [Existing-gateway cases](existing-gateway-cases.md), [Kubernetes](kubernetes-cases.md) |
| Runtime limits | The running Qwen context and completion limit match observed behavior in Docker and kind. | [Local model](cases.md), [model runtime guide](../../docs/guide/kubernetes-local.md) |
| Integrated Docker and kind journeys | The admin signs in, discovers Qwen, approves Public and Internal, gets a generated answer through the gateway, and signs out on each preview. | [Integrated demo](integrated-demo-cases.md) |

The runner reports the current suite and case totals. A smaller check can
run with repeated `--suite NAME` options, but it is not a full regression.
The latest full run reports its selected suites and case count. Review any
failed case and preserve the result, including failures; do not label a partial
run as a passing release gate. This local suite does not prove real cloud
subscription behavior, production security, image-license compliance, or
coding-session parity.
