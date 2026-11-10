# Protected kind release setup cases

**Edition:** Open Source. The setup `deploy/local/kind_protected.py` runs for
`KEEPLANE_KIND_PROTECTED=on deploy/local/kind-up.sh`, before the live
[Kubernetes developer cases](../e2e/kubernetes-developer-cases.md). The
isolated-network job reuses its steps through
`tests/fixtures/isolated-network/protected.py` for the protected release's
[isolated-network cases](../e2e/kubernetes-isolated-cases.md) (ISO-13 to
ISO-20). KPS-01 to KPS-06, KPS-08 and KPS-09 are in
`tests/unit/test_kind_protected_setup.py`; KPS-07 and KPS-10 render the chart
with Helm in `tests/integration/test_kind_protected_values.py` and are skipped
without Helm.

| ID | What to do | Expected result |
| --- | --- | --- |
| KPS-01 | Point `api.openai.com` at the fixture provider's cluster address in kind's default cluster DNS settings, then again with a new address. | One marked `hosts` block right after `ready` holds the address and falls through for every other name; everything else is unchanged. The second run replaces the block, so there is still one. |
| KPS-02 | Do the same when the settings already have a `hosts` block of their own, have no `ready` line, or the address is empty or a name. | Each is refused and nothing is written: an installer's own DNS settings are never changed. |
| KPS-03 | Make the database roles for a fresh server. | The migration, app, enroller and two status roles are login roles with no superuser, database or role creation and no inheritance; the enroller and status roles are read-only by default; the migration role owns the database; only the five roles may connect; the app role alone gets table access by default. The status roles are the chart values' two, one per gateway copy. |
| KPS-04 | Make the roles with a password that holds a quote and SQL. | Refused before any SQL is made. |
| KPS-05 | Check whether `keeplane.kind.test` points to this computer. | Only loopback addresses count; a name that doesn't resolve doesn't. The refusal says which `/etc/hosts` line to add. |
| KPS-06 | Start `kind-up.sh` with `KEEPLANE_KIND_PROTECTED=maybe`, and with `on` where `keeplane.kind.test` doesn't resolve here. | Both stop with exit 1 and a short message (the allowed values, or the `/etc/hosts` line to add) before any credential, build or cluster change. |
| KPS-07 | Render `deploy/local/protected-values.yaml` as the setup installs it, with the app image by digest. | It renders: two Ingresses on `keeplane.kind.test`, the gateway copies with `prepare-model-enroller` and `model-enroller`, CLI sign-in and the per-copy guard check on the app, both CLI clients registered and both copies' status roles paired by the migration Job, and `KEEPLANE_GATEWAY_PUBLIC_URL` `https://keeplane.kind.test/v1`. Every image is pinned by digest. Every Secret and ConfigMap the release reads is one the setup makes. |
| KPS-08 | Run the setup's install with a kubeconfig whose current context is another cluster, such as `prod-eu` or the isolated test cluster. | It stops with "Refusing Kubernetes context …" before making any credential, building anything or running any other command, so no other cluster's namespace or DNS is changed. Only `kind-keeplane` is accepted. |
| KPS-09 | Set up the isolated network's install of the same release: run its install with a kubeconfig on the local kind cluster, give it app images that are not the internal registry's by digest, and read where it puts the provider and which values it installs. | Only `kind-keeplane-isolated` is accepted: on `kind-keeplane` it stops at the context check with no other command and no credential made. The app image must be `172.30.0.200:5000/…@sha256:<digest>`; anything else is refused. The provider is the runner's address on the network, 172.30.0.1, with a certificate for `api.openai.com` and that address; the public address is `https://keeplane-protected.isolated.test`; both values files are installed, the kind release's first. No provider runs in the namespace: only the CA ConfigMap the release trusts is made. |
| KPS-10 | Render the release with the isolated network's values on top, with the app image in the internal registry by digest. | It renders with the public `/v1` address on `keeplane-protected.isolated.test`, every image pinned by digest, no `Never` pull policy, and five NetworkPolicies: app ingress and egress, gateway ingress and egress, and the migration Job's egress. The app's and the copies' egress reach the provider only at 172.30.0.1/32 on 443 and the account database; only the copies reach the gateway database. Only the ingress controller is admitted to the app and the protected port 5000. |
