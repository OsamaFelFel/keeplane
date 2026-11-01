# Kubernetes namespace permissions

Keeplane installs into one namespace. The person or pipeline that runs
`helm install`, `helm upgrade` and `helm uninstall` needs only a namespaced
Role there; no cluster-wide permission is needed. A cluster admin does a few
things once, before the first install.

This page lists both. The chart check
[`test_chart_namespace_permissions.py`](../../tests/integration/test_chart_namespace_permissions.py)
([cases](../../tests/integration/chart-namespace-permissions-cases.md)) renders
every supported installation and checks it against the example Role. These are
render checks: no live install has yet been run as a user bound only to this Role.

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
| `batch`: `jobs` | get, list, watch, create, update, patch, delete | Migration and preflight hooks, which Helm watches and then deletes |
| `policy`: `poddisruptionbudgets` | get, list, watch, create, update, patch, delete | Gateway copies' disruption budget |
| `networking.k8s.io`: `ingresses`, `networkpolicies` | get, list, watch, create, update, patch, delete | App Ingress and gateway NetworkPolicy |
| `pods`, `events`, `apps`: `replicasets` | get, list, watch | Follow rollouts and hooks with `helm --wait` and troubleshoot them |
| `pods/log` | get | Read a failed migration or preflight Job's output |

The Role has no wildcards and no access to RBAC objects, namespaces, nodes or
other cluster-scoped resources. It does not allow `escalate`, `bind` or
`impersonate`. Helm also reads the API's discovery endpoints, which
Kubernetes grants every signed-in user by default.

Anyone who can create Deployments or Jobs in the namespace can start a pod
that reads any Secret in it. Keep Keeplane in its own namespace, and do not
share the namespace with unrelated workloads or Secrets.

`helm uninstall` removes what the chart created, including the local trial's
claims and their data. It does not remove Secrets or claims the installer
created; delete those separately when they are no longer needed.

## What a cluster admin does once

1. Create the namespace: `kubectl create namespace keeplane`. Do not give the
   installer `helm install --create-namespace`; that needs a cluster-wide
   permission.
2. Apply the Role and RoleBinding:
   `kubectl apply -f deploy/examples/installer-role.yaml` (after editing the
   namespace and subject). Kubernetes lets only someone who already holds these
   permissions create the Role.
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
```
