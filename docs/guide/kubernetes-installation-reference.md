# Kubernetes installation reference

This page lists what the Keeplane Helm chart (`deploy/helm/keeplane`) expects
from an installer and what it creates. It describes the current pre-release
chart. Production storage, backup policy and the release gateway are **not
decided**. The bundled agentgateway chart is an integration trial, not the
selected release gateway.

For setup steps, see [PostgreSQL](postgres-accounts.md),
[gateway database credentials](gateway-database-secret.md),
[gateway modes](gateway-configuration.md) and the [local kind trial](kubernetes-local.md).
The [installation shape cases](../../tests/integration/chart-installation-shape-cases.md)
check this page against rendered manifests.

## Images

| Installation | App image | Managed gateway image |
| --- | --- | --- |
| PostgreSQL (`app.postgres.enabled=true`) | Must be `repository@sha256:<digest>`; Helm refuses a tag | Must be `repository@sha256:<digest>`; the default is pinned |
| Local SQLite trial (`app.localTrial.enabled=true`) | A local tag is allowed | Pinned by default |

The app copies, the provider-key init container, the migration Job and the
existing-gateway preflight Job all use the same `app.image`. The gateway chart
dependency is pinned to an exact version and vendored under `charts/`; the
[component manifest](../architecture/component-manifest.md) records the tested set.
Copy every image to your internal registry before closing registry access.

## Secrets

The chart creates no Secret objects. Create these in the release namespace and
put their names in your values. Names are your choice; the local trial uses the
names shown in brackets.

| Values field | Keys | Used by | Delivered as |
| --- | --- | --- | --- |
| `app.postgres.credentialsSecret` | `password` (restricted app role) | App copies | Read-only file, mode 0440 |
| `app.postgres.migration.credentialsSecret` | `password` (migration role) | Migration Job only | Read-only file, mode 0440 |
| `app.postgres.identitySecret` | `signing-secret`, `first-admin-password` | App copies; the Job receives only `signing-secret` | Read-only files, mode 0440 |
| `app.postgres.caSecret` | `ca.crt` | App copies and migration Job | Read-only file, mode 0440 |
| `gateway.keysSecret` (`keeplane-gateway-keys`) | `runtime-key`, `admin-key` | App copies and preflight Job | Read-only directory `/run/gateway-keys` |
| `app.localTrial.firstAdminSecret` (`keeplane-first-admin`) | `first-admin-password` | Local trial app | Read-only file |
| `ingress.tlsSecretName` | Standard TLS certificate and key | Your ingress controller | Referenced by the Ingress |
| `app.imagePullSecrets` | Registry credentials | App and Job pods | Kubernetes pull secret |

The PostgreSQL app and migration Job need separate users and Secrets; Helm
refuses a shared one. The app always connects with database TLS `verify-full`.

The managed gateway reads Secrets only through the values you give it under
`agentgateway-standalone`. Keep `${NAME}` placeholders in its database URL and
key policies, and load each `NAME` with `extraEnv` and `secretKeyRef`. The local
values load `password` from `keeplane-gateway-db`, and `runtime-key-hash` and
`admin-key-hash` from `keeplane-gateway-keys`. The chart's own default gateway
configuration sets no key policy for model calls or management, and does not
read `gateway.keysSecret`. Add both policies in your values, as the local values
do. In the local trial the app's signing key is generated on the state volume.

## Readiness

| Container | Readiness | Other checks |
| --- | --- | --- |
| App, PostgreSQL mode | `GET /health/ready` on 3000 every 5 s; returns 503 while the database is unavailable or a known migration is pending | Liveness `GET /health/app` every 20 s, which does not depend on the database |
| App, local trial | `GET /health/app` on 3000 every 5 s | Same liveness check |
| Managed gateway | `GET /healthz/ready` on 15021 every 10 s | Startup probe allows up to 60 s |

The migration Job runs before install and upgrade, with no retry and a 180 s
limit; a failure stops the Helm operation. In existing-gateway mode a preflight
Job checks the supplied gateway first, with a 90 s limit. No PodDisruptionBudget
is rendered.

## What keeps state

| State | Where it lives |
| --- | --- |
| Accounts, sessions, settings, approvals, data classes and Audit (PostgreSQL mode) | Your PostgreSQL database |
| Provider-key files (PostgreSQL mode) | Your existing claim in `app.postgres.providerKeysClaim`; the app writes it. A managed gateway mounts it read-only only if you configure that |
| Accounts, settings and signing key (local trial) | Claim `<release>-state`, `ReadWriteOnce`, `app.localTrial.storageSize` (1Gi) |
| Provider-key files (local trial) | Claim `<release>-provider-keys`, same size and access mode |
| Managed gateway model catalog | PostgreSQL at `agentgateway-standalone.database.postgres.url`; the starting configuration is in ConfigMap `<release>-config` |

All app and gateway containers run with a read-only root filesystem. The gateway
also writes temporary files to an `emptyDir` at `/tmp`. The PostgreSQL mode
renders no volume claims. The local trial allows one app copy; PostgreSQL mode
allows several, and the managed gateway defaults to two copies.

Storage class, access mode across nodes, database operation, backup schedule and
retention for a production installation are **not decided**.

## Ports

| Port | Component | Reachable through |
| --- | --- | --- |
| 3000 | App | Service `<release>-app` (`ClusterIP` by default) and the optional Ingress |
| 4000 | Managed gateway: model calls and management | Service `<release>` (`ClusterIP`) only |
| 15000 | Gateway admin | No Service; the chart keeps the gateway's loopback default |
| 15020 | Gateway stats | No Service or declared container port; pod annotations only suggest scraping |
| 15021 | Gateway readiness | No Service; used by the kubelet probe |

The optional Ingress (`ingress.enabled`) has one host, requires TLS and routes
only to the app Service. It refuses a `NodePort` app Service. The gateway is
never an Ingress backend.

`networkPolicy.gatewayIngressEnabled=true` adds one policy in managed mode. It
admits only this release's app pods, on TCP 4000, to the gateway pods. It needs
a network plugin that enforces NetworkPolicy. Any pod that can set the app's pod
label is also admitted. The chart renders no default-deny or egress policy. The
setting is refused in existing-gateway mode; protect a supplied gateway in its
own installation.

## Gateway modes

| | `managed` (default) | `existing` |
| --- | --- | --- |
| Values | `gateway.mode=managed`, `gateway.install=true` | `gateway.mode=existing`, `gateway.install=false`, `gateway.url` |
| Installs a gateway | Yes: Deployment, Service, ConfigMap and ServiceAccount from the bundled chart | No gateway objects at all; `agentgateway-standalone` values are ignored |
| App reaches the gateway at | `http://<release>:4000` | `gateway.url` |
| Before install | Nothing extra | Preflight Job checks the gateway version, model listing and management read access, and makes one call if `gateway.preflightModel` is set |
| Gateway database credential | Yours, through `agentgateway-standalone` | None given to Keeplane |

Helm refuses mismatched `mode` and `install` values. In existing mode the chart
writes no gateway configuration. The app registers models through the
gateway's management API and leaves models added outside Keeplane unchanged.
See [gateway modes](gateway-configuration.md) for the tested cases and the
limits on shared provider keys with a supplied gateway.
