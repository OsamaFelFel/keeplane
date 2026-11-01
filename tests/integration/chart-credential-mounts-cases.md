# Chart credential mount cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_credential_mounts.py`
(task 002-02, Spec 002 ST1 and ST5). CM-01 and CM-02 render the chart with
`helm template --namespace keeplane` and need Helm 3.19 or newer, found
through `KEEPLANE_HELM_BIN`, else `helm` on `PATH`. Without Helm they are
skipped, and a skipped case is not a pass. CM-03 reads only the
[installation reference](../../docs/guide/kubernetes-installation-reference.md)
and always runs.

The installations rendered are: both local trials (`deploy/local/values.yaml`
and `deploy/local/existing-values.yaml`); managed PostgreSQL, with and without
CLI sign-in; existing-gateway PostgreSQL, with and without an `https` gateway
and `gateway.caSecret`; and an existing-gateway install with only
`gateway.keysSecret` and `gateway.caSecret`, without PostgreSQL or the local
trial. Rendering proves what the chart asks Kubernetes to create, not how a
cluster's kubelet writes the files.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| CM-01 | List every Secret volume in every pod template of every installation. | Each one sets `defaultMode: 0440` (owner and group read) and no file overrides it; without the setting Kubernetes would write the files 0644, readable by every user in the container. Only Keeplane's own pods mount Secrets: the app (gateway keys, database password, database CA, identity, local-trial first-admin password, customer gateway CA), the existing-gateway preflight Job (gateway keys, customer gateway CA) and the migration Job (database password, database CA, signing secret). The gateway copies read their key hashes with `secretKeyRef` and mount no Secret. No projected volume appears. |
| CM-02 | For each pod with a Secret volume, read its `fsGroup` and every container that mounts one, init containers included. | The pod sets `fsGroup: 65532`, also in the existing-gateway install without PostgreSQL or the local trial. Every container mounting a Secret runs as user 65532, mounts it read-only and can read it through that group. The files are owned by root, so no other user in the container can read them and nobody can change them. The gateway keys reach exactly the app and the preflight Job. |
| CM-03 | Read the Secrets table of the installation reference. | Every Secret delivered as read-only files says "mode 0440", and the page explains that the files belong to the pod's `fsGroup`. |

Not covered here: the file modes a running kubelet writes on a cluster, and
Secrets an installer adds to the gateway copies through
`agentgateway-standalone.extraVolumes`, which keep the mode the installer
gives them.
