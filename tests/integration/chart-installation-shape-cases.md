# Chart installation shape cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_installation_shape.py`
with Helm 3.19 or newer. The checks find Helm through `KEEPLANE_HELM_BIN`, else
`helm` on `PATH`; without Helm they are skipped, and a skipped case is not a pass.

Each case renders the chart with `helm template` in four installations: PostgreSQL
with the managed gateway, PostgreSQL with an existing gateway, and the two local
trial values in `deploy/local/`. The PostgreSQL values are written to a temporary
file and use the documented Secret-backed gateway settings. Rendering proves what
the chart asks Kubernetes to create. It does not prove that a cluster enforces it.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| SHAPE-01 | Render both PostgreSQL installations and both local trials, then set the managed gateway image to a tag or to a registry/repository/tag map. | In PostgreSQL installs, every image is `repository@sha256:<digest>`. The local trials use a tag only for the locally built app image, as the chart allows; the gateway image stays pinned. A managed gateway image without a digest is refused in PostgreSQL mode. Existing-gateway mode ignores that setting. The gateway chart dependency has an exact version and a lock digest. |
| SHAPE-02 | List every Service, Ingress backend and declared container port. | The app Service has only port 3000. In managed mode one `ClusterIP` gateway Service has only port 4000. No Service or container port uses the gateway's admin (15000), stats (15020) or readiness (15021) ports, and the chart does not move those listeners. The Ingress routes only to the app Service on port 3000. Existing-gateway mode has only the app Service. |
| SHAPE-03 | Turn on the gateway NetworkPolicy in the managed PostgreSQL installation. | One policy selects this release's gateway pods and admits only pods labelled as this release's app, on TCP 4000. It has no namespace or address-range rule. The migration Job does not carry the admitted label. The policy is off by default and absent in existing-gateway mode. |
| SHAPE-04 | Inspect every container's environment and mounts, the gateway configuration and connection URLs. | The chart renders no Secret object. Each password, key or signing secret is either a `secretKeyRef` or a path to a file in a read-only Secret mount. The gateway configuration contains only `${...}` placeholders for its database password and key hashes, each loaded from a Secret. No URL contains a literal password. The existing-gateway app receives no gateway database credential. |
| SHAPE-05 | Inspect every Deployment's probes, root filesystem and writable mounts. | Every long-running container has a readiness probe and a read-only root filesystem. The app also has a liveness probe; the gateway has a startup probe. In PostgreSQL mode the only writable app state is the operator's provider-key claim. The local trials declare their state and provider-key claims. The gateway writes only scratch `/tmp` and keeps its catalog in PostgreSQL. Both copies run twice in the managed PostgreSQL installation. Jobs are bounded install hooks. |
| SHAPE-06 | Render existing-gateway mode while full managed-gateway settings, including an extra model, are still in the values. | Only the Keeplane app, its Service, Jobs, Ingress or trial claims render. No gateway Deployment, Service, configuration, account or policy appears, and the extra model is not written anywhere. The app points at the supplied gateway URL and gets no managed gateway configuration file. |

Not covered here: live NetworkPolicy enforcement, readiness under failure,
storage behaviour, and the managed gateway's key policies when an installer
leaves them out. The chart does not add those policies itself (see the
[installation reference](../../docs/guide/kubernetes-installation-reference.md)).
