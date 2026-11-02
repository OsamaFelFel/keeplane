# Chart namespace permission cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_namespace_permissions.py`.
NSP-04, NSP-06, NSP-07 and NSP-08 read only the example Roles in
`deploy/examples/` and the guides in `docs/guide/`, and always run. The other
cases render the chart with `helm template --namespace keeplane-permissions`
and need Helm 3.19 or newer, found through `KEEPLANE_HELM_BIN`, else `helm` on
`PATH`. Without Helm they are skipped, and a skipped case is not a pass.

The supported installations rendered are: the managed local trial
(`deploy/local/values.yaml`); managed PostgreSQL with Ingress, the gateway
NetworkPolicy, the disruption budget and an extra gateway Service turned on;
the same with CLI sign-in; the same with the
[model enroller](chart-model-enroller-cases.md) on; the existing-gateway local trial
(`deploy/local/existing-values.yaml`); existing-gateway PostgreSQL, with and
without CLI sign-in; and `deploy/postgres/values.example.yaml`. Rendering
proves what the chart asks Kubernetes to create. It does not prove that a
cluster enforces the Role; see the
[namespace permissions guide](../../docs/guide/kubernetes-namespace-permissions.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| NSP-01 | Render every supported installation and list each object's API version, kind, namespace and source template, including those from the bundled gateway chart. | Every object is one of these namespaced kinds: `v1` ConfigMap, PersistentVolumeClaim, Service and ServiceAccount; `apps/v1` Deployment and StatefulSet; `batch/v1` Job; `policy/v1` PodDisruptionBudget; `networking.k8s.io/v1` Ingress and NetworkPolicy. Together the installations render exactly this set. No ClusterRole, ClusterRoleBinding, Role, RoleBinding, CRD, Namespace, PriorityClass, StorageClass, IngressClass, webhook or other cluster-scoped object appears. No object names a namespace other than the release namespace. The bundled gateway chart adds only a ConfigMap, Service, ServiceAccount and its zero-replica Deployment. |
| NSP-02 | In managed mode, turn on the bundled gateway chart's autoscaling, its monitoring with a PodMonitor, and its `namespaceOverride`. | Helm refuses each one and names the `agentgateway-standalone` setting, so no HorizontalPodAutoscaler, no PodMonitor (which needs a cluster-wide custom resource) and no object in another namespace can be installed. |
| NSP-03 | Inspect every workload's pod template in every installation. | The app Deployment, the migration and preflight Jobs and the gateway copies' StatefulSet set `automountServiceAccountToken: false`, so their pods get no Kubernetes API token. The gateway reads its configuration from a ConfigMap file and its models from PostgreSQL and never calls the Kubernetes API. The only pod template without that setting is the bundled gateway chart's own Deployment, which has zero replicas and runs no pods. |
| NSP-04 | Read the example installer Role and RoleBinding. | Both are namespaced `rbac.authorization.k8s.io/v1` objects; the binding refers to the Role, not a ClusterRole. No rule uses a wildcard group, resource or verb, grants `escalate`, `bind` or `impersonate`, touches RBAC objects, or names a cluster-scoped resource. Write access is limited to the chart's kinds, Secrets and the app Deployment's `deployments/scale` (get, update, patch), which a restore uses to stop the app; everything else (pods, pod logs, events, ReplicaSets) is read-only. The Role grants no `pods/exec`, `pods/attach`, `pods/portforward` or proxy access, so it cannot run commands in a pod. |
| NSP-05 | Compare every kind the chart rendered in NSP-01 with the Role. | The Role grants `get`, `list`, `watch`, `create`, `update`, `patch` and `delete` on each rendered kind's resource and on Secrets, where Helm keeps its release records. |
| NSP-06 | Read the optional operations Role and RoleBinding in `deploy/examples/operations-role.yaml`. | Both are namespaced, named `keeplane-operations`, and the binding refers to that Role. It grants exactly `pods` get and list, `apps` `deployments` get, and `pods/exec` create and get (kubectl's WebSocket stream is authorized as get on API servers before Kubernetes 1.35): no Secrets, no writes, no wildcard, no RBAC or cluster-scoped resource. The installer Role still has no `pods/exec`. |
| NSP-07 | Read every `kubectl` command in the guides' shell blocks and inline code (except the permissions guide's own cluster-admin steps and the local kind trial's `--kubeconfig` commands) and work out the permissions each needs. | Every command is one the check knows (`exec`, `cp`, `get pods`, `logs`, `get`/`create`/`patch secret`, `apply` of a Secret made with `kubectl create secret --dry-run=client`, `rollout restart`, `rollout status`, `scale`, `delete networkpolicy`); a new kind of command fails until its permissions are added. Each is granted in full by the installer Role, the operations Role or both. Every guide with a command that only the operations Role grants (`kubectl exec`, `kubectl cp`) links to its section. The backup, certificate, PostgreSQL rotation and gateway key rotation guides all have such checks. |
| NSP-08 | Read the "Which Role each command needs" table in the [namespace permissions guide](../../docs/guide/kubernetes-namespace-permissions.md). | It has one row for each kind of command the guides use, no more, and each row names the Role NSP-07 works out: Operations for `kubectl exec` and `kubectl cp`, Either for `kubectl get pods`, Installer for the rest. The guide links both example files. |

Not covered here: applying the Roles in a live cluster, running
`helm install`, `helm upgrade` and `helm uninstall` as the installer, and the
guides' checks as a user bound only to the operations Role, and admission
policies a customer cluster may add.
