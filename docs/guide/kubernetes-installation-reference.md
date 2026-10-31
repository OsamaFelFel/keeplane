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
| `gateway.keysSecret` (`keeplane-gateway-keys`) | `runtime-key`, `admin-key`; with the managed gateway also `runtime-key-hash`, `admin-key-hash` | App copies and preflight Job; the managed gateway reads only the two hashes | Read-only directory `/run/gateway-keys`; the gateway gets the hashes through `secretKeyRef` |
| `app.localTrial.firstAdminSecret` (`keeplane-first-admin`) | `first-admin-password` | Local trial app | Read-only file |
| `ingress.tlsSecretName` | Standard TLS certificate and key | Your ingress controller | Referenced by the Ingress |
| `app.imagePullSecrets` | Registry credentials | App and Job pods | Kubernetes pull secret |

The PostgreSQL app and migration Job need separate users and Secrets; Helm
refuses a shared one. The app always connects with database TLS `verify-full`.

The managed gateway reads Secrets only through `extraEnv` entries with
`secretKeyRef` under `agentgateway-standalone`. Keep the `${NAME}` placeholder in
its database URL and load `NAME` that way; the local values load `password` from
`keeplane-gateway-db`. Its key policies are part of the chart: see
[gateway access keys](#gateway-access-keys). In the local trial the app's
signing key is generated on the state volume.

## Gateway access keys

The managed gateway always requires a key on port 4000. Management calls need
the admin key and model calls need the runtime key. The chart sets both policies
itself and refuses to install the managed gateway without them. The keys stay in
a Secret you create; the chart only references it and never renders a key or
key hash.

1. Create the keys and their hashes, then the Secret, in the release namespace:

   ```sh
   umask 077
   openssl rand -base64 32 | tr -d '\n' > runtime-key
   openssl rand -base64 32 | tr -d '\n' > admin-key
   for name in runtime admin; do
     printf 'sha256:%s' "$(shasum -a 256 < $name-key | cut -d ' ' -f 1)" > $name-key-hash
   done
   kubectl -n <namespace> create secret generic keeplane-gateway-keys \
     --from-file=runtime-key --from-file=admin-key \
     --from-file=runtime-key-hash --from-file=admin-key-hash
   ```

   Keep the two keys separate. Delete the local files once the Secret exists, or
   store them only where your other installation secrets live.
2. Set `gateway.keysSecret` to the Secret's name.
3. Load both hashes into the gateway. Helm cannot pass the Secret name into the
   bundled gateway chart, so add these entries to `agentgateway-standalone.extraEnv`
   next to your database password entry. The chart checks that they name the
   Secret in `gateway.keysSecret`:

   ```yaml
   agentgateway-standalone:
     extraEnv:
       - name: GATEWAY_RUNTIME_KEY_HASH
         valueFrom:
           secretKeyRef:
             name: keeplane-gateway-keys
             key: runtime-key-hash
       - name: GATEWAY_ADMIN_KEY_HASH
         valueFrom:
           secretKeyRef:
             name: keeplane-gateway-keys
             key: admin-key-hash
   ```

Helm refuses the managed install, before creating anything, when
`gateway.keysSecret` is empty, when either hash variable is missing, repeated,
given a literal value or read from another Secret, and when your values remove
or loosen `agentgateway-standalone.config.ui.policies.apiKey` or
`agentgateway-standalone.config.llm.policies.apiKey`. Do not set those two
policies in your values; the chart's are used. The
[`deploy/local/values.yaml`](../../deploy/local/values.yaml) file shows the full
form. These keys apply to the managed gateway alongside the gateway
NetworkPolicy below, so the gateway stays closed even where a cluster does not
enforce NetworkPolicy. In existing-gateway mode none of this applies: the
customer-run gateway keeps its own key setup, and `gateway.keysSecret` gives the
app and preflight Job the keys that gateway accepts.

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

All long-running app and gateway containers run with a read-only root
filesystem. The local trial's `migrate-local-database` init container is the
exception. The gateway also writes temporary files to an `emptyDir` at `/tmp`. The PostgreSQL mode
renders no volume claims. The local trial allows one app copy; PostgreSQL mode
allows several, and the managed gateway defaults to two copies
(`gateway.copies`; see [gateway copies](#gateway-copies)).

Storage class, access mode across nodes, database operation, backup schedule and
retention for a production installation are **not decided**.

## Ports

| Port | Component | Reachable through |
| --- | --- | --- |
| 3000 | App | Service `<release>-app` (`ClusterIP` by default) and the optional Ingress |
| 4000 | Managed gateway: model calls and management | Service `<release>` (`ClusterIP`), and each copy's own address through the headless Service `<release>-gateway-copies` |
| 15000 | Gateway admin | No Service; the chart keeps the gateway's loopback default |
| 15020 | Gateway stats | No Service or declared container port; pod annotations only suggest scraping |
| 15021 | Gateway readiness | No Service; used by the kubelet probe |

The optional Ingress (`ingress.enabled`) has one host, requires TLS and routes
only to the app Service. It requires a `ClusterIP` app Service and refuses
every other type, including `NodePort` and `LoadBalancer`. The gateway is
never an Ingress backend.

`networkPolicy.gatewayIngressEnabled=true` adds one policy in managed mode. It
admits only this release's app pods, on TCP 4000, to the gateway pods,
including every copy reached through its own address. It needs
a network plugin that enforces NetworkPolicy. Any pod that can set the app's pod
label is also admitted. The chart renders no default-deny or egress policy. The
setting is refused in existing-gateway mode; protect a supplied gateway in its
own installation.

## Gateway modes

| | `managed` (default) | `existing` |
| --- | --- | --- |
| Values | `gateway.mode=managed`, `gateway.install=true` | `gateway.mode=existing`, `gateway.install=false`, `gateway.url` |
| Installs a gateway | Yes: the gateway copies (StatefulSet `<release>-gateway` and headless Service `<release>-gateway-copies`), plus Service, ConfigMap, ServiceAccount and a zero-replica Deployment from the bundled chart | No gateway objects at all; `agentgateway-standalone` values are ignored |
| Gateway copies | `gateway.copies` (1–32, default 2); the app's copy list is rendered from it | Optional `gateway.copyUrls`, supplied by the installer |
| App reaches the gateway at | `http://<release>:4000` | `gateway.url` |
| Before install | Create the [gateway key Secret](#gateway-access-keys); Helm refuses the install without it | Preflight Job checks the gateway version, model listing and management read access, and makes one call if `gateway.preflightModel` is set |
| Gateway database credential | Yours, through `agentgateway-standalone` | None given to Keeplane |

Helm refuses mismatched `mode` and `install` values. In existing mode the chart
writes no gateway configuration. The app registers models through the
gateway's management API and leaves models added outside Keeplane unchanged.
See [gateway modes](gateway-configuration.md) for the tested cases and the
limits on shared provider keys with a supplied gateway.

## Gateway copies

After a model change that adds or widens access, the app reads the model back
from every gateway copy before it saves the change (see
[every gateway copy](../architecture/model-registration.md#every-gateway-copy)).
The chart sets the app's copy list, `GATEWAY_COPY_URLS`, as follows.

**Managed mode.** The bundled gateway chart runs its pods as a Deployment,
whose pods have no stable address. The chart therefore runs the managed
gateway copies itself as StatefulSet `<release>-gateway`, from the same
`agentgateway-standalone` values and ConfigMap, with headless Service
`<release>-gateway-copies`. Copy *N* is reached at
`http://<release>-gateway-<N>.<release>-gateway-copies.<namespace>.svc:4000`.
Set the number of copies with `gateway.copies` (1–32, default 2); the app's
list always has exactly that many entries. The bundled chart's own Deployment
stays at zero replicas. Helm refuses an install that:

- sets `agentgateway-standalone.replicaCount` to anything but 0, or turns on
  `agentgateway-standalone.autoscaling` (the list would no longer match the
  copies that serve);
- sets `gateway.copies` outside 1–32, or sets `gateway.copyUrls`;
- sets `agentgateway-standalone.nameOverride`, `fullnameOverride`,
  `namespaceOverride`, `extraContainers` or `oidc`.

The headless Service carries only port 4000, so the gateway's admin, stats and
readiness ports stay private. The copies carry the bundled chart's pod labels,
so the gateway Service and the gateway NetworkPolicy cover them unchanged. A
copy that is not ready has no address yet; until it is ready, changes that add
or widen access are not confirmed.

**Existing mode.** If the customer-run gateway serves through several copies,
list each copy's own management origin in `gateway.copyUrls`:

```yaml
gateway:
  mode: existing
  install: false
  url: http://customer-gateway.gateway.svc.cluster.local:4000
  copyUrls:
    - http://customer-gateway-0.customer-gateway.gateway.svc.cluster.local:4000
    - http://customer-gateway-1.customer-gateway.gateway.svc.cluster.local:4000
```

Each entry is an `http` or `https` origin: a host name or address and an
optional port, with no credentials, path, query or trailing slash. The list
holds at most 32 distinct entries. `values.schema.json` refuses anything else
before installation. Keep the list in step with the copies that serve; a copy
missing from it is never checked. Leave it empty when the gateway runs as one
copy: the gateway address is then the only copy checked.
