# Kubernetes namespace permissions

Keeplane installs into one namespace. The person or pipeline that runs
`helm install`, `helm upgrade` and `helm uninstall` needs only a namespaced
Role there; no cluster-wide permission is needed. A cluster admin does a few
things once, before the first install. Running Keeplane's checks, backups and
restores inside the app container needs one more permission, `pods/exec`,
which the installer Role leaves out; an optional
[operations Role](#operations-role) grants it separately.

This page lists all three. The chart check
[`test_chart_namespace_permissions.py`](../../tests/integration/test_chart_namespace_permissions.py)
([cases](../../tests/integration/chart-namespace-permissions-cases.md)) renders
every supported installation and checks it against the example installer Role,
and checks every `kubectl` command in the guides against the two Roles and the
[table below](#which-role-each-command-needs). These are render and text
checks: no live install or check has yet been run as a user bound only to these
Roles.

## What the chart creates

In every supported mode (managed gateway, managed gateway with PostgreSQL,
existing gateway, CLI sign-in on or off) the chart renders only these
namespaced kinds:

| Kind | API group | Rendered by | When |
| --- | --- | --- | --- |
| Deployment | `apps` | Keeplane app; bundled gateway chart (zero replicas) | Always; gateway one in managed mode |
| StatefulSet | `apps` | Managed gateway copies | Managed mode |
| Service | core | App; gateway; gateway copies (headless) | App always; gateway ones in managed mode |
| ConfigMap | core | Bundled gateway chart (gateway configuration) | Managed mode |
| ServiceAccount | core | Bundled gateway chart (gateway pod identity) | Managed mode, unless `agentgateway-standalone.serviceAccount.create=false` |
| PersistentVolumeClaim | core | Local trial state and provider keys | `app.localTrial.enabled` |
| Job | `batch` | Account migration; existing-gateway preflight (install hooks) | PostgreSQL migration on; existing mode |
| PodDisruptionBudget | `policy` | Gateway copies | `agentgateway-standalone.podDisruptionBudget.enabled` with more than one copy |
| Ingress | `networking.k8s.io` | App | `ingress.enabled` |
| NetworkPolicy | `networking.k8s.io` | Gateway ingress policy | `networkPolicy.gatewayIngressEnabled` |

The chart never renders a Namespace, ClusterRole, ClusterRoleBinding, Role,
RoleBinding, CustomResourceDefinition, PriorityClass, StorageClass,
IngressClass or webhook. Every object lands in the release namespace. Helm
refuses the bundled gateway chart's `autoscaling`, `monitoring` (its PodMonitor
needs a cluster-wide custom resource) and `namespaceOverride`.

## Kubernetes API access of the pods

No Keeplane pod gets a Kubernetes API token. The app, the migration Job, the
existing-gateway preflight Job and the managed gateway copies all set
`automountServiceAccountToken: false`. The gateway reads its configuration
from the mounted ConfigMap and its models from PostgreSQL; it never calls the
Kubernetes API.

The bundled gateway chart creates one ServiceAccount, named after the release.
No Role is bound to it. It is kept only as the gateway's pod identity, for
example to bind a cloud IAM role through its annotations
(`agentgateway-standalone.serviceAccount.annotations`). If your cluster policy
does not let Helm releases create identities, set
`agentgateway-standalone.serviceAccount.create=false` and
`agentgateway-standalone.serviceAccount.name` to an account that already exists
in the namespace. The bundled chart's own Deployment keeps its default pod
settings but runs zero replicas, so it starts no pods.

## Installer Role

[`deploy/examples/installer-role.yaml`](../../deploy/examples/installer-role.yaml)
holds the Role and a RoleBinding. Replace the namespace `keeplane` and the
subject (group `keeplane-installers`) with your own.

| Resources | Verbs | Why |
| --- | --- | --- |
| `configmaps`, `persistentvolumeclaims`, `serviceaccounts`, `services` | get, list, watch, create, update, patch, delete | Objects the chart and the bundled gateway chart manage; the installer also creates the provider-key claim in PostgreSQL mode |
| `secrets` | get, list, watch, create, update, patch, delete | Secrets the installer creates before installing (gateway keys, database credentials, identity material, TLS), and Helm's own release records, which Helm keeps in Secrets in the release namespace |
| `apps`: `deployments`, `statefulsets` | get, list, watch, create, update, patch, delete | App, gateway copies, bundled zero-replica Deployment |
| `apps`: `deployments/scale` | get, update, patch | Stop and start the app copies during a [PostgreSQL restore](backup-and-restore.md#postgresql) with `kubectl scale`; patching the Deployment can already change its replica count |
| `batch`: `jobs` | get, list, watch, create, update, patch, delete | Migration and preflight hooks, which Helm watches and then deletes |
| `policy`: `poddisruptionbudgets` | get, list, watch, create, update, patch, delete | Gateway copies' disruption budget |
| `networking.k8s.io`: `ingresses`, `networkpolicies` | get, list, watch, create, update, patch, delete | App Ingress and gateway NetworkPolicy |
| `pods`, `events`, `apps`: `replicasets` | get, list, watch | Follow rollouts and hooks with `helm --wait` and troubleshoot them |
| `pods/log` | get | Read a failed migration or preflight Job's output |

The Role has no wildcards and no access to RBAC objects, namespaces, nodes or
other cluster-scoped resources. It does not allow `escalate`, `bind` or
`impersonate`, and it cannot run commands in pods (`pods/exec`, `pods/attach`,
`pods/portforward`). Helm also reads the API's discovery endpoints, which
Kubernetes grants every signed-in user by default.

Anyone who can create Deployments or Jobs in the namespace can start a pod
that reads any Secret in it. Keep Keeplane in its own namespace, and do not
share the namespace with unrelated workloads or Secrets.

`helm uninstall` removes what the chart created, including the local trial's
claims and their data. It does not remove Secrets or claims the installer
created; delete those separately when they are no longer needed.

## Operations Role

The checks and the backup and restore steps in the guides run commands inside
the `app` container: `manage.py check_credentials`, `manage.py verify_restore`,
the `mounted_sha` comparison during a rotation, and the SQLite and
provider-key copies of a backup or restore. `kubectl exec` and `kubectl cp`
need `pods/exec`, which the installer Role does not grant.
[`deploy/examples/operations-role.yaml`](../../deploy/examples/operations-role.yaml)
holds a separate Role, `keeplane-operations`, and a RoleBinding for that.
Replace the namespace `keeplane` and the subject (group `keeplane-operators`)
with your own. Skip it if nobody runs these steps, or if the person who does
already has `pods/exec` in the namespace.

| Resources | Verbs | Why |
| --- | --- | --- |
| `pods` | get, list | Find the app pods: `kubectl exec deploy/<release>-app` reads the Deployment and lists its pods; some steps pick a pod by label |
| `apps`: `deployments` | get | The same lookup |
| `pods/exec` | create, get | Run the command (`kubectl exec`, `kubectl cp`). kubectl opens the stream with a POST, or from kubectl 1.31 with a WebSocket GET, which API servers before Kubernetes 1.35 authorize as `get` |

It has no access to Secrets through the Kubernetes API and cannot create,
change or delete anything. It is still powerful: a command in the `app`
container can read everything the app can, including the database passwords,
the signing secret, the gateway keys and the developers' provider-key folder.
Bind it only to people you already trust with those Secrets, and consider
binding it only for as long as they need it. Kubernetes cannot limit
`pods/exec` to the app pods; it also covers the gateway copies in the same
namespace.

### Which Role each command needs

Each `kubectl` command in the guides needs the permissions in this table.
"Either" means both Roles grant it.

| Command in the guides | Permissions | Role |
| --- | --- | --- |
| `kubectl exec` (checks, backup and restore copies) | `pods/exec` create and get; `pods` get and list; `deployments` get | Operations |
| `kubectl cp` (SQLite trial backup) | `pods/exec` create and get; `pods` get | Operations |
| `kubectl get pods` | `pods` get and list | Either |
| `kubectl logs` | `pods/log` get; `pods` list | Installer |
| `kubectl get secret` | `secrets` get | Installer |
| `kubectl create secret` | `secrets` create | Installer |
| `kubectl apply` (a Secret from `kubectl create secret --dry-run=client`) | `secrets` get, create and patch | Installer |
| `kubectl patch secret` | `secrets` get and patch | Installer |
| `kubectl rollout restart` | `deployments` or `statefulsets` get and patch | Installer |
| `kubectl rollout status` | `deployments` get and watch; `replicasets` list | Installer |
| `kubectl scale` | `deployments/scale` get and patch | Installer |
| `kubectl delete networkpolicy` | `networkpolicies` delete | Installer |

A rotation, backup or restore that changes Secrets or restarts the app and
also runs a check needs both Roles. The commands on this page itself, and the
local trial's commands with `--kubeconfig`, run as a cluster admin.

## What a cluster admin does once

1. Create the namespace: `kubectl create namespace keeplane`. Do not give the
   installer `helm install --create-namespace`; that needs a cluster-wide
   permission.
2. Apply the Role and RoleBinding:
   `kubectl apply -f deploy/examples/installer-role.yaml` (after editing the
   namespace and subject). Kubernetes lets only someone who already holds these
   permissions create the Role. Apply
   `deploy/examples/operations-role.yaml` the same way if someone will run the
   documented checks, backups or restores.
3. With `ingress.enabled`, make sure the IngressClass named in
   `ingress.className` exists and its controller runs. IngressClasses are
   cluster-scoped; the installer only names one.
4. With `networkPolicy.gatewayIngressEnabled`, make sure the cluster's network
   plugin enforces NetworkPolicy. Without one the policy is accepted but has no
   effect.
5. Make sure a StorageClass can provide the claims the
   [installation reference](kubernetes-installation-reference.md) lists, and
   that the nodes can pull the pinned images, or give the installer the pull
   Secret's name.
6. Apply any namespace labels, quotas or admission policies your cluster uses.
   The chart has not been tested against Pod Security admission levels or
   customer admission policies.

The installer can then check its access before installing, for example:

```sh
kubectl auth can-i --list --namespace keeplane
kubectl auth can-i create clusterroles   # expected: no
kubectl auth can-i create pods --subresource=exec --namespace keeplane   # yes only with the operations Role
```
