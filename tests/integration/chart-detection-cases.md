# Chart personal-data detection cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_detection.py`
(tasks 005-03 and 002-02, Spec 005 ST20 and Spec 002 ST1). CD-01 to CD-05 and CD-08
render the chart with `helm template --namespace keeplane` and need Helm 3.19
or newer, found through `KEEPLANE_HELM_BIN`, else `helm` on `PATH`. Without
Helm they are skipped, and a skipped case is not a pass. CD-06 and CD-07 read
only the values file and the guides and always run.

Rendering proves what the chart asks Kubernetes to run, not that the detector
loads in a cluster. The image side (offline load under a read-only root
filesystem, memory and start-up time) is
[DI-01](detection-image-cases.md), and the app's readiness
while the model loads is PD-12 and PD-13 in
[the detection rules](../unit/personal-data-detection-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| CD-01 | Render managed and existing-gateway PostgreSQL installs and both local trials with the default values. | No object sets `KEEPLANE_PERSONAL_DATA_DETECTION`; app readiness stays `/health/ready` for PostgreSQL and `/health/app` for the local trial, as before. |
| CD-02 | Render an existing-gateway PostgreSQL install with `app.personalDataDetection.enabled` off, then on. | The only change is `KEEPLANE_PERSONAL_DATA_DETECTION: "1"` on the app container; no Job, gateway or preflight gets it. Every other rendered line is the same, so every security default stays and no init container, volume or download step is added. |
| CD-03 | Render the existing-gateway local trial with detection off, then on, and the PostgreSQL install with it on. | The local trial gains the setting and its readiness moves to `/health/ready`, which waits for the model's first load; nothing else changes. In both, liveness stays `/health/app`, the app keeps a read-only root filesystem, user 65532 and no service account token. |
| CD-04 | With detection on, set `app.resources.limits.memory` to 1Gi or more in several forms (`1Gi`, `1024Mi`, `1536Mi`, `2Gi`, `1.5Gi`, bytes as text or a number, `1100M`, `2G`); then below 1Gi (`512Mi`, `1023Mi`, `1G`, `1000M`, `0.5Gi`, one byte under, a number, `900Mi`); then unreadable (`lots`, `1 Gi`, `1gi`, `1e9`, `-1Gi`). | The first set renders with the limit. Each one below 1Gi is refused with "app.personalDataDetection needs app.resources.limits.memory of at least 1Gi"; the same limit with detection off renders. Each unreadable one is refused, asking for bytes or a unit such as 1536Mi or 2Gi. |
| CD-05 | Turn detection on with the managed gateway (PostgreSQL and the local trial), set the value to text, or add an unknown key under it. | Helm refuses the managed installs, saying detection requires `gateway.mode=existing` because the managed gateway in this chart doesn't run Keeplane's checks yet. The values schema refuses text and unknown keys. |
| CD-08 | Turn detection on with the existing gateway and neither `app.postgres` nor `app.localTrial`; then with each of them. | Helm refuses the first, saying detection needs `app.postgres` or `app.localTrial` because the app would never become ready without a database; the same install with detection off gets no detection refusal, and each of the others renders. |
| CD-06 | Read `values.yaml`. | `app.personalDataDetection.enabled` is `false` and its comment names the install setting, the `postgres-detection` target, offline loading, the 1Gi minimum and the existing-gateway requirement. |
| CD-07 | Read the installation reference's Personal-data detection section and the data classes guide. | The reference names the value, the three detection image targets, the install setting, the 1Gi minimum and suggested 1536Mi limit, `/health/ready`, the read-only root filesystem, no download, the existing-gateway requirement, the "isn't installed" message for an image without the detector and network policies. The data classes guide links to it and names `postgres-detection`. |

Not covered here: Helm cannot see which image target `app.image` was built
from, so an image without the detector is reported by the app, not refused by
Helm (PD-13). A live install on a cluster, the native gateway cases with the
setting on, and enforcement of the memory limit by a kubelet have not run.
