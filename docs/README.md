# Keeplane documentation

| Task | Guide |
| --- | --- |
| Start locally, change the port or troubleshoot | [Run locally](guide/local-preview.md) |
| Try the experimental local coding adapter | [CLI prototype](../components/cli/README.md) |
| Sign in, code and resume private history | [Signed-in coding](guide/cli-coding.md) |
| Create accounts and change roles | [Accounts](guide/accounts-local.md) |
| Add, edit or remove a model | [Model setup](guide/model-add-local.md), [model approvals](guide/model-approval-local.md) |
| See or change the model for each complexity level | [Complexity levels](guide/complexity-levels.md), [how picks are stored](architecture/complexity-levels.md) |
| Send a persona's work to a chosen model | [Persona rules](guide/persona-rules.md), [how a task's model is chosen](architecture/task-routing.md) |
| Enable data classes | [Data classes](guide/data-classes-local.md) |
| Hold requests with personal data to a stricter class | [Detect personal data](guide/data-classes-local.md#detect-personal-data-in-requests), [how requests are checked](architecture/runtime-authorization.md#personal-data-detection) |
| Find recorded events | [Audit](guide/audit-local.md), [keep and export records](guide/audit-storage.md), [Audit storage design](architecture/audit-storage.md) |
| Use a managed or customer-run gateway | [Gateway configuration](guide/gateway-configuration.md) |
| Try Kubernetes deployment | [Kubernetes](guide/kubernetes-local.md) |
| Check Secrets, readiness, storage, ports and gateway modes for a Kubernetes install | [Kubernetes installation reference](guide/kubernetes-installation-reference.md) |
| Open only the connections Keeplane needs on an isolated network | [Outbound connections](guide/outbound-connections.md) |
| Give an installer only the permissions a Kubernetes install needs in one namespace | [Kubernetes namespace permissions](guide/kubernetes-namespace-permissions.md) |
| Configure PostgreSQL, credentials and recovery | [PostgreSQL](guide/postgres-accounts.md), [gateway database credentials](guide/gateway-database-secret.md) |
| Create the model enroller's database roles for each gateway copy | [Enroller database roles](guide/guard-status-roles.md), [per-copy guard status](architecture/runtime-authorization.md#per-copy-guard-status) |
| Back up and restore Keeplane's data | [Back up and restore](guide/backup-and-restore.md) |
| See when certificates expire and renew them without a restart | [Check and renew certificates](guide/certificate-operations.md) |
| Preview an existing Claude, Codex or Qwen project setup | [CLI migration preview](guide/cli-migration-preview.md) |
| Run tests and retain their results | [Testing](guide/regression-local.md) |
| Check the MVP journey end to end on the preview | Admin half: [demo cases](../tests/e2e/integrated-demo-cases.md); developer half, DEV-01 to DEV-05: [developer journey cases](../tests/e2e/developer-journey-cases.md), [try it by hand](guide/local-preview.md#try-the-developer-half-by-hand) |
| Read the experimental allowed-model catalog | [Runtime catalog](guide/runtime-catalog.md) |
| See your own tokens and estimated cost per model | [`keeplane usage`](guide/cli-usage.md) |
| Report and read a developer's own token usage per model | [Usage API](guide/runtime-catalog.md#report-and-read-your-own-usage), [how usage is kept](architecture/developer-usage.md) |
| Test internal gateway policy decisions | [Runtime authorization](architecture/runtime-authorization.md) |
| Understand the components | [Architecture](architecture/local-preview.md) |
| Find the exact component versions tested together | [Component manifest](architecture/component-manifest.md) |

Start with the guide for your task. These documents describe the current
development application and identify unfinished behavior where it affects use.
