# Certificate operations

These cases cover the certificate part of task 002-02 (Spec 002 ST1, ST4 and
ST5): seeing when the certificates Keeplane checks expire, and renewing them
without a restart. The installer's steps are in
[check and renew certificates](../../docs/guide/certificate-operations.md).
The chart's part is in
[chart certificate cases](../integration/chart-certificates-cases.md).

Each case makes its own CA and server certificates with the `openssl` command
and runs small local TLS servers: one that answers PostgreSQL's TLS request
first, as a database server does, and one that answers HTTPS like a gateway.
Nothing is kept in Git. The cases are skipped where `openssl` is missing.
Cases CO-01 to CO-09 are in `test_certificate_checks.py`, CO-10 to CO-13
(the app's bundle for the chart's `trust.extraCaBundle`, built by
`components/control-plane/prepare_trust_bundle.py`) in `test_trust_bundle.py`.

| Case | Given | Expected result |
| --- | --- | --- |
| CO-01 A CA bundle is listed | A CA file holding an old and a new CA, as during a CA rotation | Both are listed in order with subject, issuer, SHA-256 fingerprint (equal to `openssl x509 -fingerprint -sha256`), expiry date (equal to `openssl x509 -enddate`) and days left. The report holds no PEM block or private key. |
| CO-02 Expiry status | One certificate checked at several moments | More than 30 days before expiry it is `valid`; 12 days before it is `expires soon` with 12 days left and a warning sentence; after expiry it is `expired` with a refusal sentence; before its start date it is `not yet valid`. |
| CO-03 Unreadable CA file | A missing file, an empty file, a block that is not base64, and a block that is not a certificate | Each is a refusal naming the problem: cannot be read, holds no certificate, or holds a certificate that cannot be read. |
| CO-04 Database server certificate | A PostgreSQL-style server presenting a certificate from the new CA, valid for 20 days | Trusted with the new CA file only, as libpq's `sslrootcert` with `verify-full`; reported as `expires soon`. With the old CA file it is untrusted ("unable to get local issuer certificate") but its dates are still shown. A certificate for another name is reported as "does not match localhost"; a server that refuses TLS as "does not offer TLS". |
| CO-05 `check_credentials` and certificate expiry | A database CA file and a database server certificate valid for 400 days; a plain-HTTP gateway | The report has `database_ca` and `database_server` and nothing for the HTTP gateway; the check passes. Ten days before the server certificate expires it is a warning and the check still passes; after the CA expires it is a refusal and the check fails. A warning window of 500 days lists the server certificate as a warning without failing. |
| CO-06 Gateway CA renewed under a running app | An HTTPS gateway with a certificate from a private CA, called by one app adapter that is never restarted | Without a mounted CA the call fails as "Gateway unavailable"; with a missing CA file as "Gateway CA unavailable". With the CA mounted the call succeeds. The CA file then holds old and new CA, the gateway switches to a certificate from the new CA, and the file is reduced to the new CA: every call succeeds. `check_credentials` lists the new CA and the trusted gateway certificate. Putting back only the old CA makes calls fail and the check names the gateway. |
| CO-07 The gateway CA file is reloaded only when it changes | The same CA file read twice, then changed | The same trust is reused while the file is unchanged and rebuilt after it changes. |
| CO-08 Preflight and an untrusted gateway | The existing-gateway preflight against an HTTPS gateway from a private CA | Without the CA it fails at once with "Gateway TLS certificate is not trusted:" and the reason. With the CA it reads the gateway. |
| CO-09 CLI with a private CA | An HTTPS Keeplane server whose certificate comes from a private CA | The CLI refuses with "Cannot reach Keeplane securely; check the server and certificate configuration." With `SSL_CERT_FILE` naming the CA it reads the account. |
| CO-10 Extra CAs are added after the system CAs | A stand-in system CA file with a public CA, and an extra bundle with a comment line, two private CAs and Windows line endings | The written file starts with the system file unchanged, then holds the two CAs (three in all, no comment, no `\r`), with mode 0444 and no partial file left. With only the system file, Python trusts a server from the public CA and not one from the private CA; with the written file it trusts both. |
| CO-11 A malformed bundle stops the pod | No certificate, an empty file, damaged base64, a block that isn't a certificate, a private key, a CRL, a file over 1 MiB, a missing file, and an empty system CA file | Each is refused with a reason ("holds no PEM certificate", "holds a damaged certificate", "holds a private key", "holds a X509 CRL block", "is larger than 1 MiB", "can't be read", "holds no certificate"), the command exits 1 with "Keeplane can't use trust.extraCaBundle: …", and nothing is written. A missing system file is refused rather than trusting only the extra CAs. No key text is printed. |
| CO-12 The image's real system CA file | This machine's own OpenSSL CA file and one extra CA | The command exits 0 and prints "System CAs kept: N. Extra CAs added: 1.", N being the CAs in that file, which the written file starts with. |
| CO-13 The gateway's copy holds only checked CAs | `--extra-only` with a bundle of a comment line and two CAs, then a bundle with a private key | The first writes only the two certificates (no system CA, no comment), mode 0444, and prints "Extra CAs written for the gateway: 2." The second exits 1 with "Keeplane can't use trust.extraCaBundle: The extra CA bundle holds a private key. Give only CA certificates, never a key." and writes nothing. A missing output path is a usage error. |

Not covered here: a renewal on a live cluster, an ingress controller reloading
its Secret, cert-manager, a real PostgreSQL server's certificate change and
whether the coding tool started by the CLI honours `SSL_CERT_FILE`.
