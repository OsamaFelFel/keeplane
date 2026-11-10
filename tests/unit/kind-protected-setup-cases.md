# Protected kind release setup cases

**Edition:** Open Source. The setup `deploy/local/kind_protected.py` runs for
`KEEPLANE_KIND_PROTECTED=on deploy/local/kind-up.sh`, before the live
[Kubernetes developer cases](../e2e/kubernetes-developer-cases.md). KPS-01 to
KPS-06 are in `tests/unit/test_kind_protected_setup.py`; KPS-07 renders the
chart with Helm in `tests/integration/test_kind_protected_values.py` and is
skipped without Helm.

| ID | What to do | Expected result |
| --- | --- | --- |
| KPS-01 | Point `api.openai.com` at the fixture provider's cluster address in kind's default cluster DNS settings, then again with a new address. | One marked `hosts` block right after `ready` holds the address and falls through for every other name; everything else is unchanged. The second run replaces the block, so there is still one. |
| KPS-02 | Do the same when the settings already have a `hosts` block of their own, have no `ready` line, or the address is empty or a name. | Each is refused and nothing is written: an installer's own DNS settings are never changed. |
| KPS-03 | Make the database roles for a fresh server. | The migration, app, enroller and two status roles are login roles with no superuser, database or role creation and no inheritance; the enroller and status roles are read-only by default; the migration role owns the database; only the five roles may connect; the app role alone gets table access by default. The status roles are the chart values' two, one per gateway copy. |
| KPS-04 | Make the roles with a password that holds a quote and SQL. | Refused before any SQL is made. |
| KPS-05 | Check whether `keeplane.kind.test` points to this computer. | Only loopback addresses count; a name that doesn't resolve doesn't. The refusal says which `/etc/hosts` line to add. |
| KPS-06 | Start `kind-up.sh` with `KEEPLANE_KIND_PROTECTED=maybe`, and with `on` where `keeplane.kind.test` doesn't resolve here. | Both stop with exit 1 and a short message (the allowed values, or the `/etc/hosts` line to add) before any credential, build or cluster change. |
| KPS-07 | Render `deploy/local/protected-values.yaml` as the setup installs it, with the app image by digest. | It renders: two Ingresses on `keeplane.kind.test`, the gateway copies with `prepare-model-enroller` and `model-enroller`, CLI sign-in and the per-copy guard check on the app, both CLI clients registered and both copies' status roles paired by the migration Job, and `KEEPLANE_GATEWAY_PUBLIC_URL` `https://keeplane.kind.test/v1`. Every image is pinned by digest. Every Secret and ConfigMap the release reads is one the setup makes. |
