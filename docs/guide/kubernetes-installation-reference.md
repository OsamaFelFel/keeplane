# Kubernetes installation reference

This page lists what the Keeplane Helm chart (`deploy/helm/keeplane`) expects
from an installer and what it creates. It describes the current pre-release
chart. Production storage, backup policy and the release gateway are **not
decided**. The bundled agentgateway chart is an integration trial, not the
selected release gateway.

For setup steps, see [PostgreSQL](postgres-accounts.md),
[gateway database credentials](gateway-database-secret.md),
[gateway modes](gateway-configuration.md) and the [local kind trial](kubernetes-local.md).
To check certificate expiry dates and renew certificates, see
[check and renew certificates](certificate-operations.md).
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
| `gateway.caSecret` (existing mode, optional) | `ca.crt`: the CA of an `https` customer-run gateway | App copies and preflight Job, in addition to the image's system CAs | Read-only file, mode 0440 |
| `ingress.tlsSecretName` | Standard TLS certificate and key | Your ingress controller | Referenced by the Ingress; see [renew the public HTTPS certificate](certificate-operations.md#renew-the-public-https-certificate) |
| `app.imagePullSecrets` | Registry credentials | App and Job pods | Kubernetes pull secret |

The PostgreSQL app and migration Job need separate users and Secrets; Helm
refuses a shared one. The app always connects with database TLS `verify-full`.
Every Secret is mounted without `subPath`, so a renewed CA or rotated password
reaches running pods. `manage.py check_credentials` reports the expiry date of
each certificate Keeplane checks; see
[check and renew certificates](certificate-operations.md).

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
   openssl rand -hex 32 | tr -d '\n' > runtime-key
   openssl rand -hex 32 | tr -d '\n' > admin-key
   for name in runtime admin; do
     printf 'sha256:%s' "$(shasum -a 256 < $name-key | cut -d ' ' -f 1)" > $name-key-hash
   done
   kubectl -n <namespace> create secret generic keeplane-gateway-keys \
     --from-file=runtime-key --from-file=admin-key \
     --from-file=runtime-key-hash --from-file=admin-key-hash
   ```

   A key may hold only letters, digits, `-` and `_`, 32 to 256 of them; Keeplane
   refuses any other runtime key. `openssl rand -hex 32` makes 64 such
   characters. Don't use `openssl rand -base64`: its keys can hold `+`, `/` and
   `=`. Keep the two keys separate. Delete the local files once the Secret
   exists, or store them only where your other installation secrets live.
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
policies in your values; the chart's are used. The one exception is a key
rotation, which may add a second hash, `${GATEWAY_ADMIN_KEY_HASH_NEXT}` or
`${GATEWAY_RUNTIME_KEY_HASH_NEXT}`, read from the same Secret; see
[rotate the gateway keys](gateway-configuration.md#rotate-the-gateway-keys).
The
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

The chart can also limit who reaches these ports and where Keeplane's pods
connect; see [network policies](#network-policies).

## Network policies

All policies are off by default. They need a network plugin that enforces
NetworkPolicy; the local kind preview (kindnet) does not, so keep them off
there. **The chart's render checks prove which policies Helm creates and which
pods they select. They do not prove that your cluster enforces them.** After
installing, check from a pod that should be refused, for example with a call
that must time out. The [network policy cases](../../tests/integration/chart-network-policies-cases.md)
list what the render checks cover.

| Setting | Policy | Pods selected | Allows only |
| --- | --- | --- | --- |
| `gatewayIngressEnabled` (managed mode) | `<release>-gateway-ingress` | Gateway copies | In: this release's app pods, TCP 4000 |
| `appIngressEnabled` | `<release>-app-ingress` | App pods | In: the pods matching `publicEntry`, TCP 3000 |
| `egressEnabled` | `<release>-app-egress` | App pods | Out: DNS; the gateway copies on TCP 4000 (managed) or `egress.suppliedGateway` (existing); `egress.postgres`; `egress.modelEndpoints`; `egress.runners` |
| `egressEnabled` (managed mode) | `<release>-gateway-egress` | Gateway copies | Out: DNS; `egress.gatewayDatabase` (database mode); `egress.modelEndpoints` |
| `egressEnabled` (PostgreSQL with the chart's migration Job) | `<release>-accounts-migrate-egress` | Migration Job | Out: DNS; `egress.postgres` |
| `egressEnabled` (existing mode) | `<release>-gateway-preflight-egress` | Preflight Job | Out: DNS; `egress.suppliedGateway` |

All settings sit under `networkPolicy`. Each selected pod is denied every
connection in that direction that its policy does not list.

**Public entry.** `publicEntry.namespaceSelector` and `publicEntry.podSelector`
are label maps for your ingress controller, for example
`kubernetes.io/metadata.name: ingress-nginx` and
`app.kubernetes.io/name: ingress-nginx`. Give at least one; a namespace map
alone admits every pod in that namespace, and a pod map alone means pods in the
release namespace. Helm refuses `appIngressEnabled` without either, and with an
app Service other than `ClusterIP`. No other Keeplane pod calls the app: the
gateway copies make no call to it and the Jobs call only PostgreSQL or the
supplied gateway. The kubelet's readiness and liveness checks come from the
node, which most network plugins admit regardless of policy; check yours.

**Destinations.** Each entry in an `egress` list is either an address range or
labels, with the TCP ports to allow:

```yaml
networkPolicy:
  appIngressEnabled: true
  publicEntry:
    namespaceSelector:
      kubernetes.io/metadata.name: ingress-nginx
  egressEnabled: true
  egress:
    modelEndpoints:
      - cidr: 203.0.113.0/24        # a provider outside the cluster
        ports: [443]
      - namespaceSelector:          # a runner inside the cluster
          kubernetes.io/metadata.name: models
        podSelector:
          app: qwen
        ports: [8080]
    postgres:
      - cidr: 10.20.0.5/32
        ports: [5432]
    gatewayDatabase:
      - namespaceSelector:
          kubernetes.io/metadata.name: database
        podSelector:
          app: gateway-db
        ports: [5432]
```

Use labels for anything that runs in the cluster: an address range for a pod or
Service address is not reliable, because pod addresses change and most plugins
check the pod address behind a Service, not the Service address. Use `cidr` for
destinations outside the cluster. NetworkPolicy cannot match host names: if a
model provider has no fixed addresses, you must either allow a wide range on
port 443 or send that traffic through an egress proxy you run, and list the
proxy instead.

`dns` defaults to the cluster DNS pods (`k8s-app: kube-dns` in `kube-system`)
on UDP and TCP 53. Replace both label maps, or set them to `null` and give
`dns.cidr` instead, for example for a node-local DNS cache.

`egress.modelEndpoints` lists every model provider and runner the gateway
copies call. The app also gets these endpoints because it checks provider keys
and probes providers itself. `egress.runners` is optional and lists the runner
addresses in `app.runnerUrls` that the app checks directly.

Helm refuses `egressEnabled`, before creating anything, when:

- `egress.modelEndpoints` is empty;
- PostgreSQL is on (`app.postgres.enabled`) and `egress.postgres` is empty;
- the managed gateway runs in database mode and `egress.gatewayDatabase` is empty;
- the gateway is customer-run (existing mode) and `egress.suppliedGateway` is empty.

Helm also refuses settings for objects the chart does not install, whether or
not the policies are on: `gatewayIngressEnabled` or `egress.gatewayDatabase` in
existing mode, `egress.suppliedGateway` in managed mode, `egress.gatewayDatabase`
with a read-only gateway, and `egress.postgres` without PostgreSQL. An entry
with both `cidr` and labels, or with an empty label map, is refused too, since
an empty selector would match everything. `values.schema.json` refuses unknown
settings, address ranges that are not CIDRs, and ports outside 1–65535.

**Customer-run gateway.** In existing mode the chart creates no policy for the
gateway. It restricts only Keeplane's pods: list the supplied gateway in
`egress.suppliedGateway`, covering `gateway.url` and every `gateway.copyUrls`
host, by labels if it runs in the cluster or by address range otherwise.
Protect the gateway itself in its own installation.

**Install Jobs.** The migration and preflight Jobs run before install and
upgrade, so their policies are install hooks that Helm creates first. Helm
does not remove hook objects on uninstall, or when you later turn
`egressEnabled` off: delete `<release>-accounts-migrate-egress` and
`<release>-gateway-preflight-egress` with `kubectl delete networkpolicy` then.

Any pod that can carry the app's pod label (`app: <release>-app`) is treated as
the app by the gateway ingress policy. Restricting who may set that label is
outside this chart.

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
  `namespaceOverride`, `extraContainers` or `oidc`;
- turns on `agentgateway-standalone.monitoring`. The copies declare no
  metrics port, so the gateway's metrics stay private.

The copies take the image and pull policy exactly as the bundled chart writes
them: a registry/repository map with a bare version tag such as `1.6.0` becomes
`v1.6.0`, and a map without a tag uses the bundled chart's version. Like the
bundled chart, the copies restart only when a setting agentgateway reads at
startup changes (the nested `config` section other than `config.modelCatalog`,
and the database address); model and route changes are reloaded without a
restart. With `agentgateway-standalone.podDisruptionBudget.enabled` and more
than one copy, the chart adds the disruption budget `<release>-gateway` over
the copies, using that setting's `minAvailable` or `maxUnavailable`. With one
copy no budget renders, so a node drain is never blocked.

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
