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
existing-gateway preflight Job all use the same `app.image`. To install
[personal-data detection](#personal-data-detection), build that image from a
detection target. The gateway chart
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
| `gateway.keysSecret` (`keeplane-gateway-keys`) | `runtime-key`, `admin-key`; with the managed gateway also `runtime-key-hash`, `admin-key-hash` | App copies and preflight Job; the managed gateway reads only the two hashes | Read-only directory `/run/gateway-keys`, files mode 0440; the gateway gets the hashes through `secretKeyRef` |
| `app.localTrial.firstAdminSecret` (`keeplane-first-admin`) | `first-admin-password` | Local trial app | Read-only file, mode 0440 |
| `gateway.caSecret` (existing mode, optional) | `ca.crt`: the CA of an `https` customer-run gateway | App copies and preflight Job, in addition to the image's system CAs | Read-only file, mode 0440 |
| `ingress.tlsSecretName` | Standard TLS certificate and key | Your ingress controller | Referenced by the Ingress; see [renew the public HTTPS certificate](certificate-operations.md#renew-the-public-https-certificate) |
| `app.imagePullSecrets` | Registry credentials | App and Job pods; the gateway copies too with the model enroller | Kubernetes pull secret |
| `gateway.enroller.approvalsSecret` (optional) | `password` (enroller approvals role) | [Model enroller](#model-enroller) init step only | `secretKeyRef` environment value, written for the enroller to an in-memory file |
| `gateway.enroller.statusSecret` (optional) | `copy-0-password`, `copy-1-password`, … (one status role per gateway copy) | [Model enroller](#model-enroller) init step only; each copy's enroller gets only its own | `secretKeyRef` environment values, written for the enroller to an in-memory file |

The PostgreSQL app and migration Job need separate users and Secrets; Helm
refuses a shared one. The app always connects with database TLS `verify-full`.
Every Secret is mounted without `subPath`, so a renewed CA or rotated password
reaches running pods. Every mounted Secret file has mode 0440: Kubernetes makes
it owned by root, with the pod's group 65532 (`fsGroup`), so Keeplane's
non-root user 65532 can read it, other users cannot, and nobody can change it
([CM-01, CM-02](../../tests/integration/chart-credential-mounts-cases.md)). `manage.py check_credentials` reports the expiry date of
each certificate Keeplane checks; see
[check and renew certificates](certificate-operations.md).

The managed gateway reads its database password and key hashes only through
`extraEnv` entries with `secretKeyRef` under `agentgateway-standalone`. Keep
the `${NAME}` placeholder in its database URL and load `NAME` that way; the
local values load `password` from
`keeplane-gateway-db`. Its key policies are part of the chart: see
[gateway access keys](#gateway-access-keys). In the local trial the app's
signing key is generated on the state volume.

Prefer `secretKeyRef` for anything else the managed gateway needs. If it must
read a Secret as files, add a `secret` volume (or a `projected` volume with a
`secret` source) to `gateway.extraVolumes`, and mount it with
`gateway.extraVolumeMounts`. Only the gateway copies get these volumes. Helm
refuses `agentgateway-standalone.extraVolumes` and `extraVolumeMounts`: the
bundled gateway chart's own Deployment, which runs zero copies, would list them
without the checks below, so a Secret there would carry Kubernetes' usual
0644 if that Deployment were ever scaled up.

The gateway copies get Secret files with mode 0440 when the volume sets no
mode. Helm keeps a stricter mode, such as 0400, and refuses a looser one: any
write or execute bit, or any access for other users, such as Kubernetes' usual
0644. Write a mode as an octal number with a leading 0, such as `0440`;
without it YAML reads a decimal number, so `440` means 0670 and is refused,
and a quoted `"0440"` is text and is refused too. Because the files belong to
root, the non-root gateway can read 0440 files only through the pod's group,
so Helm also refuses a Secret volume unless
`agentgateway-standalone.podSecurityContext.fsGroup` is set (for example to
65532); Kubernetes then adds group read, so 0400 files are written 0440. With
`app.postgres` or `app.localTrial` the gateway shares the provider-key volume
and Helm refuses any gateway `fsGroup`, so those installs cannot mount Secret
files into the gateway and use `secretKeyRef` instead
([CM-04 to CM-06, CM-08, CM-09](../../tests/integration/chart-credential-mounts-cases.md)).
With `gateway.mode=existing` the chart runs no gateway, so it ignores these
settings. The chart offers no extra volumes for the app.

```yaml
gateway:
  extraVolumes:
    - name: provider-ca
      secret:
        secretName: provider-ca   # mounted with mode 0440
  extraVolumeMounts:
    - name: provider-ca
      mountPath: /run/provider-ca
      readOnly: true
agentgateway-standalone:
  podSecurityContext:
    fsGroup: 65532
```

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
| App, with `app.personalDataDetection.enabled` | `GET /health/ready` in both modes; also returns 503 while the detector's language model loads for the first time, for at most 300 s | Same liveness check, which never waits for the model |
| Managed gateway | `GET /healthz/ready` on 15021 every 10 s | Startup probe allows up to 60 s |

The migration Job runs before install and upgrade, with no retry and a 180 s
limit; a failure stops the Helm operation. In existing-gateway mode a preflight
Job checks the supplied gateway first, with a 90 s limit. No PodDisruptionBudget
is rendered.

## Personal-data detection

Detection is off by default and stays an admin choice: the chart only
installs it, and an admin then turns it on under **Data classes** (see
[data classes](data-classes-local.md#detect-personal-data-in-requests)).
Request text is checked inside the app; nothing is downloaded at install or at
run time.

1. Build the app image from a detection target of
   `components/control-plane/Dockerfile`, push it to your registry and pin it
   by digest:

   | Installation | Image target |
   | --- | --- |
   | PostgreSQL | `postgres-detection` |
   | PostgreSQL with `app.cliSignIn.enabled` | `postgres-cli-auth-detection` |
   | Local SQLite trial | `detection` |

   ```sh
   docker build -f components/control-plane/Dockerfile --target postgres-detection \
     -t registry.example.com/keeplane-app:detection .
   ```

   The build is the only step that downloads the detector: its packages and
   the `en_core_web_lg` language model are installed with pinned hashes and
   baked into the image, with their notices under `/usr/share/keeplane/licenses`.
   The image is about 750 MiB larger.

2. Set the chart value. It adds `KEEPLANE_PERSONAL_DATA_DETECTION=1` to the
   app container and changes nothing else:

   ```yaml
   app:
     image: registry.example.com/keeplane-app@sha256:<digest>
     personalDataDetection:
       enabled: true
     resources:
       requests:
         memory: 1Gi
       limits:
         memory: 1536Mi
   ```

3. Set up Keeplane's checks on your gateway so that they send each request's
   messages, as in
   [Keeplane's checks on a customer-run gateway](gateway-configuration.md#keeplanes-checks-on-a-customer-run-gateway).

Helm refuses an install that:

- turns detection on without `app.postgres` or `app.localTrial`. The app is
  ready only once its database and the language model are, and without either
  setting the chart gives it no database, so it would never become ready;
- turns detection on with the managed gateway. Requests reach Keeplane's
  checks only on a customer-run gateway for now (`gateway.mode=existing`); the
  managed gateway in this chart doesn't run them yet, so no request would be
  checked;
- sets `app.resources.limits.memory` below 1Gi, or writes it in a form other
  than bytes or a unit such as `1536Mi` or `2Gi`. The language model alone uses
  about 750 MiB once loaded. We suggest a 1Gi request and a 1536Mi limit;
- sets `app.personalDataDetection.enabled` to anything but `true` or `false`.

Helm can't see what an image contains, so it can't refuse an `app.image`
built without the detector. That install still starts: the app logs
"KEEPLANE_PERSONAL_DATA_DETECTION=1 is set, but this app image has no
personal-data detector or model" and the Data classes page says "Personal-data
detection isn't installed. Install it, then turn this on.", so detection can't
be turned on. Check the log after the first install or upgrade with
`kubectl logs deployment/<release>-app`.

At run time:

- **Start-up.** Each app copy loads the model from the image as it starts,
  whenever detection is installed, even while the admin switch under Data
  classes is off, so it uses about 750 MiB from the start; set the memory as
  above (1536Mi limit suggested). Readiness
  (`/health/ready`) answers 503 until that first load finishes, so a new copy
  takes no requests during a rollout until it can check them; liveness doesn't
  wait. If the load fails or takes longer than 300 s, the copy becomes ready
  anyway and, while detection is on, holds every request it can't check to the
  detection class.
- **Memory and CPU.** About 750 MiB of memory per app copy for the model. Each
  check must finish within 200 ms, so on a busy or CPU-limited copy more long
  requests are held; give the app at least one full CPU if requests are held
  for being slow.
- **Read-only root filesystem.** The app keeps `readOnlyRootFilesystem`,
  user 65532, no added capabilities and no Kubernetes API token. The model is
  read from the image and the detector writes no files, so it needs no extra
  volume.
- **No download.** The detector never fetches a model or a public-suffix list;
  if the model is missing it reports itself unavailable. With
  [network policies](#network-policies) on, it needs no destination beyond
  those the app already has.

## What keeps state

| State | Where it lives |
| --- | --- |
| Accounts, sessions, settings, approvals, data classes and Audit (PostgreSQL mode) | Your PostgreSQL database |
| Provider-key files (PostgreSQL mode) | Your existing claim in `app.postgres.providerKeysClaim`; the app writes it. A managed gateway mounts it read-only only if you add it to `gateway.extraVolumes` and `gateway.extraVolumeMounts`. With the [model enroller](#model-enroller) the gateway copy Pods always mount it read-only, so it must be mountable wherever they run |
| Accounts, settings and signing key (local trial) | Claim `<release>-state`, `ReadWriteOnce`, `app.localTrial.storageSize` (1Gi) |
| Provider-key files (local trial) | Claim `<release>-provider-keys`, same size and access mode |
| Managed gateway model catalog | PostgreSQL at `agentgateway-standalone.database.postgres.url`; the starting configuration is in ConfigMap `<release>-config` |
| A gateway copy's guard (with the [model enroller](#model-enroller)) | Pod-local `emptyDir` `keeplane-guard`, lost when the Pod is replaced; what each copy confirmed is in the guard-status table in your PostgreSQL database |

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
| `egressEnabled` (managed mode) | `<release>-gateway-egress` | Gateway copies | Out: DNS; `egress.gatewayDatabase` (database mode); `egress.modelEndpoints`; `egress.postgres` with the [model enroller](#model-enroller) |
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

Each copy's Pod name is also its name in the gateway guard-status table, which
the private model enroller for that copy will write (Helm refuses it until the
chart installs the protected runtime); see
[model enroller](#model-enroller).

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

## Model enroller

With the managed gateway and PostgreSQL, the chart holds Keeplane's private
model enroller ([ADR 027](../architecture/runtime-authorization.md#model-enroller)),
which runs beside every gateway copy. It is off by default
(`gateway.enroller.enabled: false`).

> **Helm refuses the enroller for now.** The enroller keeps a copy's
> protected checks in step with the saved models, but this chart doesn't yet
> install Keeplane's protected runtime on the managed gateway (its guard,
> callback key and first enrolment). An enroller would have no guard to keep
> and every protected model would stay refused, so Helm refuses
> `gateway.enroller.enabled: true` with a message saying so, as it refuses
> personal-data detection with the managed gateway. The rest of this section
> describes what the chart will run once that runtime is installed; you can
> already create the roles and Secrets.

`app.guardStatusCheck` (`KEEPLANE_GUARD_STATUS_CHECK=1`) can be on only
together with the enroller, so it can't be on yet either.

**What runs.** Each gateway copy Pod of StatefulSet `<release>-gateway` gets:

- an init container, `prepare-model-enroller`, that writes this copy's
  credentials into an in-memory folder and exits (see Secrets below);
- a `model-enroller` container running `manage.py run_model_enroller` from
  `app.image`. It shares the copy's network namespace, so it reads the copy's
  loopback-only applied state at `127.0.0.1`, and it opens no port: no Service,
  probe or Ingress reaches it. Both containers run as user 65532 with a
  read-only root file system, no privilege escalation and every capability
  dropped. The Pod still gets no Kubernetes API token and the chart adds no
  ServiceAccount, Role or other kind.

The copy's guard lives in a Pod-local `emptyDir` (`keeplane-guard`) at
`/installed`: the enroller mounts it read-write, the gateway container
read-only, and the app never mounts it. The folder belongs to user 65532 with
mode 0700, as in the Docker preview, so the gateway reads it only as that
user: Helm refuses an `agentgateway-standalone` `securityContext` or
`podSecurityContext` that sets another `runAsUser`. The enroller also mounts
`app.postgres.providerKeysClaim` read-only at `/provider-keys` to check
shared-key files, so that claim must be mountable on every node where the
gateway copies run. Its resources come from `gateway.enroller.resources`; Helm
refuses an install without both a CPU and a memory limit (defaults: requests
25m and 128Mi, limits 500m and 384Mi). With `app.imagePullSecrets`, the
gateway copy Pods get them too, since the enroller uses the app image.

**Database roles.** Create the roles first, as in
[the enroller's database roles](guard-status-roles.md): one read-only
approvals role for every enroller, and one status role per gateway copy.

```yaml
gateway:
  copies: 2
  enroller:
    enabled: true
    approvalsUser: keeplane_enroller
    approvalsSecret: keeplane-enroller-db     # key: password
    statusRoles:                              # entry N is <release>-gateway-N
      - keeplane_status_0
      - keeplane_status_1
    statusSecret: keeplane-guard-status-db    # keys: copy-0-password, copy-1-password
```

`statusRoles` lists exactly `gateway.copies` roles, in copy order. Role names
use lowercase letters, digits and underscores, and every role differs from the
others and from `app.postgres.user` and `app.postgres.migration.user`. With
the chart's migration Job (`app.postgres.migration.enabled`), the Job runs
`manage.py configure_guard_status_access` after every `migrate`, naming the app
role, the approvals role and each copy's Pod name with its status role, so the
grants and row-level security follow `gateway.copies` on every upgrade. If you
run migrations yourself, run that command too, as in the roles guide. When you
change `gateway.copies`, create the new roles and add their passwords first.

**Secrets.** Both Secrets are made by you and only referenced by the chart:

| Values field | Keys |
| --- | --- |
| `gateway.enroller.approvalsSecret` | `password`: the approvals role's password |
| `gateway.enroller.statusSecret` | `copy-0-password`, `copy-1-password` and so on: each status role's password |

The gateway Pod has no `fsGroup` with PostgreSQL, so Secret files mounted there
could be read only by root (see [Secrets](#secrets)). The credentials therefore
reach only the init container, as `secretKeyRef` environment values, none of
them optional: the two passwords above, `app.postgres.caSecret` (`ca.crt`) and
`gateway.keysSecret` (`admin-key`, `runtime-key`). The init container picks
this copy's status role and password by its Pod name, so an enroller never
holds another copy's status password, and writes them, mode 0400, into an
in-memory `emptyDir` that only the enroller mounts, read-only. It also writes a
random signing secret of the enroller's own: the enroller signs nothing and
never gets `app.postgres.identitySecret`. The gateway container gets none of
these, and the app's and migration's Secrets never reach the gateway Pod. Helm
refuses an enroller Secret that is also the app's, the migration's, the
identity or the gateway keys Secret.

Because the init container copies the credentials when the Pod starts, a
rotated password, key or CA reaches the enroller only after you restart the
copies (`kubectl rollout restart statefulset <release>-gateway`). Restart them
after updating a Secret and before retiring the old credential.

**The app's check.** While the enroller runs, the app also gets
`KEEPLANE_GUARD_STATUS_CHECK=1`: a protected check from a gateway copy counts
only when that copy's guard-status row lists the model (see
[per-copy guard status](../architecture/runtime-authorization.md#per-copy-guard-status)).
It can't be turned off while the enroller runs, and Helm refuses
`app.guardStatusCheck: true` without the enroller: no copy would confirm a
model, so every protected check would be refused.

**Network policies.** With `networkPolicy.egressEnabled`, the gateway copies'
egress policy also allows `networkPolicy.egress.postgres` while the enroller
runs. A policy covers the whole Pod, so the gateway container gets that path
too, but no database credential. Nothing new is reachable from outside.

Helm refuses, before creating anything:

- `gateway.enroller.enabled` in every install for now, until the chart
  installs the protected runtime (see the note above);
- `gateway.enroller.enabled` with `gateway.mode=existing`: Keeplane writes no
  guard on a customer-run gateway, whose checks read the saved approvals on
  every request;
- `gateway.enroller.enabled` without `app.postgres`;
- `app.guardStatusCheck` without the enroller, or with `gateway.mode=existing`;
- a gateway `runAsUser` other than 65532;
- a missing or malformed `approvalsUser`, a `statusRoles` list that doesn't
  match `gateway.copies`, a shared role, a missing `approvalsSecret` or
  `statusSecret`, or a missing CPU or memory limit;
- a Pod name over 63 characters (`<release>-gateway-<N>`), which can't name a
  copy;
- a `gateway.extraVolumes` entry named `keeplane-guard`,
  `keeplane-enroller-files` or `keeplane-enroller-provider-keys`, or a
  `gateway.extraVolumeMounts` entry at or under `/installed`.

The [model enroller chart cases](../../tests/integration/chart-model-enroller-cases.md)
check this section against rendered manifests. While the enroller is refused,
they render a test copy of the chart without that one refusal. They prove what
the chart asks Kubernetes to run, not a live run on a cluster or on the real
gateway image.
