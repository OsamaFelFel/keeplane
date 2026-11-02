# Chart model enroller cases

Run `.venv/bin/python -m pytest tests/integration/test_chart_model_enroller.py`
(tasks 004-01 and 002-02, Spec 004 ST10 and ST23–ST25, Spec 002 ST1, ST4 and
ST5, [ADR 027](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0027-model-enroller.md)).
ME-01 to ME-09 render the chart with `helm template --namespace keeplane` and
need Helm 3.19 or newer, found through `KEEPLANE_HELM_BIN`, else `helm` on
`PATH`. Without Helm they are skipped, and a skipped case is not a pass. ME-10
reads only the values file and the guides and always runs.

Installs use the managed PostgreSQL values of the
[installation shape cases](chart-installation-shape-cases.md), release `pg`,
with the enroller settings the
[installation reference](../../docs/guide/kubernetes-installation-reference.md#model-enroller)
shows. The [namespace permission](chart-namespace-permissions-cases.md) and
[credential mount](chart-credential-mounts-cases.md) cases also render an
install with the enroller on. The init step itself is
[EF-01 to EF-07](../unit/model-enroller-files-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ME-01 | Render managed and existing-gateway PostgreSQL installs and both local trials with the default values. | Nothing about the enroller renders: no `KEEPLANE_GUARD_STATUS_CHECK`, enroller container, init step, guard folder, `/installed` mount or `configure_guard_status_access`. |
| ME-02 | Turn the enroller on. | Each gateway copy Pod runs `agentgateway` and `model-enroller`, after the init step `prepare-model-enroller`; there are still two copies and no API token. The enroller runs `manage.py run_model_enroller --callback-host pg-app:3000` from the app image, declares no port or probe, runs as user 65532 with a read-only root, no privilege, no escalation, every capability dropped and the runtime's default seccomp profile, and has CPU and memory requests and limits; so does the init step. It reaches the gateway on `127.0.0.1:4000`, reads approvals as `keeplane_enroller` with `KEEPLANE_DATABASE_READ_ONLY=1` and `verify-full`, takes its copy name from the Pod name, and reads every credential from a file under `/run/keeplane-enroller/files`, never from a setting. It mounts the guard read-write at `/installed`, its files and the provider-key claim read-only. |
| ME-03 | Compare the copies with the enroller off and on. | The gateway container gains only a read-only mount of the guard at `/installed`; its settings, image and security are unchanged. The Pod gets no `fsGroup` and no Secret or projected volume: the guard is a 16Mi `emptyDir`, the enroller's files a 1Mi in-memory `emptyDir` that only the init step and the enroller mount, and the provider-key claim is mounted read-only by the enroller only. |
| ME-04 | With one, two and three copies, list where the init step's values come from. | Exactly: `password` of the approvals Secret, `copy-<N>-password` of the status Secret for each copy, `ca.crt` of `app.postgres.caSecret`, and `admin-key` and `runtime-key` of `gateway.keysSecret`, none optional. The copy prefix is `pg-gateway-` and the status roles are listed in copy order. The app's database Secret, the identity Secret and the migration Secret appear nowhere in the gateway Pod. |
| ME-05 | Turn the enroller on; then ask for the check without it; then turn the check off while the enroller runs. | The app container gets `KEEPLANE_GUARD_STATUS_CHECK=1` in all three, and no other object gets it. |
| ME-06 | Turn the enroller on with three copies, then with CLI sign-in too. | The migration Job runs `migrate`, then `configure_guard_status_access` with the app role, the approvals role and `pg-gateway-0` to `pg-gateway-2` paired with their status roles. With CLI sign-in the client registration runs between them. |
| ME-07 | Turn on the egress policies with and without the enroller. | With it, `pg-gateway-egress` gains exactly the `networkPolicy.egress.postgres` rule after its existing rules; without it, it has no such rule. |
| ME-08 | Give the app a pull secret and turn the enroller on. | The same objects render as without it (no new kind or name), and the gateway copy Pods get the app's pull secret, which they didn't before. |
| ME-09 | Try unsafe or incomplete settings: the enroller or the check with `gateway.mode=existing`; either on the local trial (no PostgreSQL); a missing or upper-case approvals role; too few status roles or more copies than roles; a role with a dash; a shared status role; the approvals role equal to the app role, or a status role equal to the migration role; a missing approvals or status Secret; the app's database Secret or the gateway keys Secret as an enroller Secret; no limits, or no memory limit; an extra gateway volume named `keeplane-guard`; an extra mount at `/installed/`; a 53-character release name with 32 copies; unknown keys or wrong types under `gateway.enroller`; the check as text. | Helm refuses each one, with a message naming the setting and why: the managed-gateway rule, "needs app.postgres", "must name", "gateway.copies is 2, but 1 roles are listed", "statusRoles[1]", "needs its own roles", "is required", "must be Secrets of their own", "limits needs cpu and memory", the reserved volume name or path, and "must be at most 63 characters" naming `…-gateway-31`. The same long release name with 10 copies renders. The values schema refuses the wrong keys and types. |
| ME-10 | Read `values.yaml`, the installation reference's Model enroller section, the roles guide and the runtime authorization page. | The values file has `gateway.enroller.enabled: false`, `app.guardStatusCheck: false` and comments for every enroller setting. The reference names every value and Secret key, `KEEPLANE_GUARD_STATUS_CHECK`, `configure_guard_status_access`, the existing-gateway refusal, `secretKeyRef`, no port, `networkPolicy.egress.postgres` and the restart a rotation needs. The roles guide links to it and the runtime authorization page names `gateway.enroller`. |

Not covered here: rendering proves what the chart asks Kubernetes to run, not
a live run. The chart doesn't yet install Keeplane's checks on the managed
gateway or run the first enrolment, so on a cluster the enroller would find no
guard to keep. A live install, the files the kubelet writes, a NetworkPolicy
that a plugin enforces, and a run on the real gateway image have not run.
