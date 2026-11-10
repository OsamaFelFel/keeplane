# Kind preview: a model provider behind a private CA

These cases run the chart's `trust.extraCaBundle` (Spec 009 ST30) on the kind
preview. `deploy/local/kind-up.sh` makes a new test CA and a certificate for
the fixture provider `cloud-provider` on every start, in
`kind-cloud-provider-tls/` in the credential directory, and deletes the CA's
private key once it has signed. The fixture serves HTTPS on
`https://cloud-provider:18443/v1` with Secret `cloud-provider-tls`, and
`deploy/local/values.yaml` names ConfigMap `cloud-provider-ca` (the CA only) in
`trust.extraCaBundle`. Keeplane sends provider keys only over HTTPS, so this is
the address the preview's cloud models use.

`test_kind_private_ca.py` runs them after `test_kind.py` in the **Kubernetes
live checks** workflow, refuses any context but `kind-keeplane`, signs in as
the first admin from the local password file and never prints a key. It removes
the models it adds. The chart's render checks are CO-H6 to CO-H11 in
[chart certificate cases](../integration/chart-certificates-cases.md).

| ID | What to do | Expected result |
| --- | --- | --- |
| KCA-01 | Read the app's trust file inside the app pod and compare it with the image's own system CA file, and read each gateway copy's pod. | The app's `SSL_CERT_FILE` is `/run/keeplane-trust/ca-bundle.pem`. That file starts with the image's system CA file unchanged and ends with the test CA from `cloud-provider-ca`: one certificate more than the system file, and Python's default context loads at least that many CAs. Both gateway copies have `SSL_CERT_DIR=/run/keeplane-extra-ca` with `cloud-provider-ca` mounted there, and no `SSL_CERT_FILE` of their own, so the image's system CA file stays. |
| KCA-02 | As the admin, add an OpenAI model for developers' own keys, approved for Public data. | It is added (200) and listed with `key_choice` `personal`. Adding it makes the app check the provider over HTTPS, which works only because the app trusts the test CA. |
| KCA-03 | As the admin, add an OpenAI model with the preview's shared key, ask it a question through Keeplane, then send the same question straight to each gateway copy with the app's runtime key. | It is added, Keeplane's answer is "mock cloud answer" and each copy answers "mock cloud answer". The fixture provider counts at least three more answers to the shared key (by its hash): over HTTPS from the gateway copies, which trust the test CA. |

Not covered here: a developer saving their own key and a task's request
running on it, as DEV-10 does on the Docker preview
([developer journey cases](developer-journey-cases.md)). Saving a developer key
needs CLI sign-in, and a request on it needs the guarded gateway with the model
enroller; the chart offers both only with `app.postgres`, and the kind preview
runs the SQLite local trial. Also not covered: whether a gateway copy still
trusts a public CA, which would need a request to an outside provider. The
render checks show its system CA file is kept, and the gateway reads the file
and the folder together.
