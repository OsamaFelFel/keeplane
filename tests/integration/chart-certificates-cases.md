# Chart certificate settings

These cases render the Helm chart and check how certificates reach Keeplane
and the ingress (task 002-02, Spec 002 ST1 and ST5). They are in
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
