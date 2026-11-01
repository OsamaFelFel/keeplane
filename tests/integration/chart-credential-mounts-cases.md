# Chart credential mount cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_credential_mounts.py`
(task 002-02, Spec 002 ST1, ST4 and ST5). CM-01, CM-02 and CM-04 to CM-06
render the chart with
`helm template --namespace keeplane` and need Helm 3.19 or newer, found
through `KEEPLANE_HELM_BIN`, else `helm` on `PATH`. Without Helm they are
skipped, and a skipped case is not a pass. CM-03 and CM-07 read only the
guides and always run.

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
| CM-04 | Install with the managed gateway and neither PostgreSQL nor the local trial (the only installs whose gateway may set `fsGroup`), with the gateway's `fsGroup` 65532 and three Secret volumes in `agentgateway-standalone.extraVolumes` that set no mode: a `secret`, a `secret` listing one file, and a `projected` volume with a `secret` and a `configMap` source. Render the same values with an existing gateway, and render the local trial. | On the gateway copies each of the three gets `defaultMode: 0440` and no per-file mode, and the pod keeps `fsGroup: 65532`, so only the gateway's group can read the files. The copies' own ConfigMap and temporary volumes are unchanged. The bundled gateway chart's Deployment lists the volumes as given but runs no pods (0 replicas). The local trial's gateway, which mounts the shared provider-key volume without `fsGroup`, renders as before. With an existing gateway the chart runs no gateway and no pod mounts the volumes. |
| CM-05 | The same managed install with stricter modes: `defaultMode` 0400 on a `secret`; 0440 with one file at 0400; and a `projected` volume at 0040 with one `secret` file at 0400. | Helm keeps every mode exactly as given. |
| CM-06 | The same managed install with a mode looser than 0440: 0644 (Kubernetes' usual mode), 0444, 0640, 0460, 0550 or 04440 on a `secret`; 0644 on one listed file; 0644 on a `projected` volume; 0604 on one file of a projected `secret`; the mode written as text "0440"; or any Secret volume (no mode, 0440, or projected) while the gateway pod has no `fsGroup`. Then add a Secret volume to a PostgreSQL install, with and without a gateway `fsGroup`, and render the 0644 volume without `fsGroup` with an existing gateway. | Helm refuses each managed install. A looser mode gets "accept only owner and group read (0440) or stricter", text gets "is not a number", and a missing `fsGroup` gets "podSecurityContext.fsGroup is unset", because root owns the files and the non-root gateway could read them only if every user could; each names `agentgateway-standalone.extraVolumes[0]`. The PostgreSQL gateway shares the provider-key volume, so its `fsGroup` gets "Leave the managed gateway fsGroup unset" and without one the volume is refused as above: such installs give the gateway Secrets through `secretKeyRef` only. The existing-gateway install renders, with no gateway pod. |
| CM-07 | Read the Secrets section of the installation reference and the gateway modes guide. | The reference says a Secret in `agentgateway-standalone.extraVolumes` gets mode 0440, a stricter mode is kept, a looser one such as 0644 is refused, the gateway needs `podSecurityContext.fsGroup`, PostgreSQL and local-trial installs, whose gateway shares the provider-key volume, cannot set it and use `secretKeyRef`, `gateway.mode=existing` ignores these settings and the chart has no extra volumes for the app. The gateway modes guide points there. |

Not covered here: the file modes a running kubelet writes on a cluster (with
`fsGroup` set, Kubernetes adds group read, so a 0400 file is written 0440),
and credentials reaching the gateway through other volume types, such as a
CSI secrets driver, whose modes the driver sets.
