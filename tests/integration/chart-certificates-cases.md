# Chart certificate settings

These cases render the Helm chart and check how certificates reach Keeplane
and the ingress (task 002-02, Spec 002 ST1 and ST5), and how an extra CA
bundle (`trust.extraCaBundle`, Spec 009 ST30) reaches the app and the managed
gateway copies. They are in
`test_chart_certificates.py` and are skipped where Helm is missing. Rendering
proves what the chart asks Kubernetes to create, not that a certificate is
valid or served. The installer's steps are in
[check and renew certificates](../../docs/guide/certificate-operations.md);
the certificate checks themselves are in
[certificate operations cases](../unit/certificate-operations-cases.md). The
database CA mounts are covered by CR-07 and CR-08 in
[credential rotation cases](credential-rotation-cases.md).

| Case | Given | Expected result |
| --- | --- | --- |
| CO-H1 Gateway CA mounted | Existing mode with an `https` gateway and `gateway.caSecret=customer-gateway-ca` | The app copies and the preflight Job get `KEEPLANE_GATEWAY_CA_FILE=/run/keeplane-gateway-ca/ca.crt`, a read-only mount of that Secret, and no `subPath`, so a renewed CA reaches running pods. No Secret is rendered. |
| CO-H2 No gateway CA, no change | Existing and managed mode without `gateway.caSecret` | Nothing about a gateway CA is rendered. |
| CO-H3 Managed gateway refuses a gateway CA | Managed mode with `gateway.caSecret` set | Helm refuses the install and names `caSecret`. |
| CO-H4 Ingress TLS Secret | PostgreSQL mode with the Ingress on | The Ingress names `ingress.tlsSecretName` for `ingress.host`, which is also its only rule host; no Secret is rendered. Without `ingress.tlsSecretName` Helm refuses: "ingress.tlsSecretName is required when ingress is enabled". |
| CO-H5 Mounted certificates are readable | Existing mode with `gateway.caSecret` and PostgreSQL | The app, the preflight Job and the migration Job each run as non-root user 65532. Every CA and key Secret they mount (mode 0440, root-owned) belongs to the pod's `fsGroup` 65532, so that user can read it. Without the preflight Job's `fsGroup`, its gateway CA would be unreadable and every install would fail. |
| CO-H6 Extra CAs, managed mode | `trust.extraCaBundle` names Secret `model-endpoint-ca`, key `bundle.pem`; two gateway copies, then three with the model enroller | The app pods run init container `prepare-trust-bundle` (app image, user 65532, read-only root) with only that key mounted as `ca.crt` (mode 0440, pod `fsGroup` 65532), and the app's `SSL_CERT_FILE` is the combined file in an in-memory folder; the app never mounts the source. Each gateway copy's `agentgateway` container gets `SSL_CERT_DIR=/run/keeplane-extra-ca` and that one file (mode 0444: the copies have no `fsGroup`), and no `SSL_CERT_FILE`, so the image's own system CA file stays. No other container in the copy gets it, the enroller included. No Secret or ConfigMap is rendered. |
| CO-H7 Extra CAs, existing mode | `trust.extraCaBundle` names ConfigMap `model-endpoint-ca`, with `gateway.caSecret` too | The app trusts the bundle as in CO-H6, from the ConfigMap. No gateway copies are rendered, the preflight Job is unchanged, and the customer-run gateway's CA keeps its own `KEEPLANE_GATEWAY_CA_FILE`. |
| CO-H8 Off by default | Managed and existing mode without `trust.extraCaBundle`, and with only its default `key` | Nothing about extra CAs is rendered: no `SSL_CERT_FILE`, `SSL_CERT_DIR`, volume or init container. |
| CO-H9 A malformed reference is refused | Both `secretName` and `configMapName`; a name with capitals, `/`, a leading `-` or over 253 characters; an empty key, `../ca.crt` or `..`; an unknown field, a list or a number | Helm refuses each and names the field: "set secretName or configMapName, not both", "… is not a Kubernetes object name", "… is not a Secret or ConfigMap key". The schema refuses the unknown field and wrong types. |
| CO-H10 The gateway's system CAs can't be replaced alongside it | Managed mode with the bundle and `SSL_CERT_FILE` or `SSL_CERT_DIR` in `agentgateway-standalone.extraEnv` | Helm refuses: "Leave SSL_CERT_FILE out of agentgateway-standalone.extraEnv …", since either would replace the system CAs. Existing mode, which runs no gateway, renders. |
| CO-H11 The kind preview's fixture provider | `deploy/local/values.yaml` | The app's provider addresses are `https://cloud-provider:18443/v1`, and the app and gateway copies trust ConfigMap `cloud-provider-ca` as in CO-H6. |

CO-H6 to CO-H11 are in `test_chart_certificates.py` too. The bundle builder's
own checks are CO-10 to CO-12 in
[certificate operations cases](../unit/certificate-operations-cases.md), and the
kind preview runs the bundle live in
[private CA cases](../e2e/kubernetes-private-ca-cases.md).
