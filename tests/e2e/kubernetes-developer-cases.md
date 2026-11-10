# Protected developer path on Kubernetes

**Edition:** Open Source. Spec 009 ST29 and ST30 (ADR 028, ADR 030), Spec 002
tasks 002-02 and 002-03, and Spec 004 task 004-01 (the model enroller,
ADR 027), on a kind cluster. The same developer steps as DEV-06, DEV-09 and
DEV-10 in [developer-journey-cases.md](developer-journey-cases.md), which run on
the Docker preview, here against a Helm release with the chart's own options.

Run on the local kind cluster with the protected developer release, then the
suite with the pinned coding runtime, OpenCode V2 2.0.27 (the musl build the
`coding-runtime` check downloads and hash-checks):

```sh
echo "127.0.0.1 keeplane.kind.test" | sudo tee -a /etc/hosts
KEEPLANE_KIND_PROTECTED=on deploy/local/kind-up.sh
KEEPLANE_OPENCODE_V2_BIN=/path/to/opencode \
  .venv/bin/python -m pytest tests/e2e/test_kind_protected.py -m live
```

The **Chart on a kind cluster** job of the **Kubernetes live checks** workflow
runs it on every pull request, after the SQLite trial's cases, in Alpine (the
runtime is built for musl) on the runner's network, and fails if any case is
skipped or missing. Without `KEEPLANE_OPENCODE_V2_BIN`, KDEV-01 still runs,
KDEV-02 to KDEV-04 are reported as not run and the suite is skipped. It also
skips, with the reason, when the Kubernetes context isn't `kind-keeplane`,
the release's test CA is missing or its gateway copies aren't ready.

## The release

`deploy/local/kind_protected.py` installs Helm release `keeplane` in namespace
`keeplane-protected`, fresh on every start, from
[`deploy/local/protected-values.yaml`](../../deploy/local/protected-values.yaml):

- the `postgres-cli-auth-trial` app image, loaded into kind and pinned by its
  digest, with `app.postgres` (two app copies) and `app.cliSignIn`; the
  migration Job registers both CLI clients and sets the enroller's grants;
- the managed gateway, two copies, with `gateway.enroller`: each copy runs
  Keeplane's protected runtime and its model enroller, with the approvals
  role and one status role per copy, created as
  [guard-status-roles.md](../../docs/guide/guard-status-roles.md) shows;
- `ingress.enabled` on `keeplane.kind.test` with ingress-nginx
  (`controller-v1.15.1`, every image by digest) on the node's port 443,
  published on this computer's loopback. The app's Ingress serves `/`; the
  protected Ingress serves only `/v1/chat/completions`. The chart sets
  `KEEPLANE_GATEWAY_PUBLIC_URL` to `https://keeplane.kind.test/v1`;
- `trust.extraCaBundle` with the release's test CA.

## Fixtures

- A test CA, new on every start, signs the account database's certificate
  (`db`), the public address's (`keeplane.kind.test`) and the fixture
  provider's (`api.openai.com`, `cloud-provider`); its key is deleted once it
  has signed. Its certificate is in `<runtime>/kind-protected/ca.pem`, which
  the developers' CLIs and the suite trust (`SSL_CERT_FILE`).
- The account database: PostgreSQL that accepts only TLS with a password,
  with Keeplane's migration and app roles, the enroller's approvals role and
  two status roles. The gateway database: `postgres-fixture.yaml`.
- The HTTPS fixture provider of the kind preview
  ([`cloud_provider.py`](../fixtures/cloud_provider.py),
  `cloud-provider-fixture.yaml`), its own copy in the namespace. Inside the
  cluster the name `api.openai.com` points to it (a `hosts` entry in the
  cluster DNS), so the app's key checks and the gateway copies' model calls
  for OpenAI models reach only the fixture, over HTTPS with the test
  certificate. It accepts the trial's shared key, and a developer key once the
  suite marks that key's SHA-256 as accepted (refused, as a revoked key). It
  records only key hashes, never a key.
- Two temporary developers, created by the first admin. Each has a private
  home folder, the source-tree CLI and the runtime on their `PATH`, and runs
  over SSH with no display, so `keeplane login` uses the device code.
- Two models the admin adds through the **Add model** API, approved for Public
  data: `gpt-5-mini` from OpenAI on the shared key, and `gpt-4.1-mini` from
  OpenAI for developers' own keys. The suite waits until both copies' model
  enrollers report the two models enrolled.
- A sample Git repo per developer with the same remote, so one project.

Afterwards the suite signs both CLIs out and removes the two models and the
developers. It doesn't wait for the enrollers to settle: the next start
replaces the namespace.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| KDEV-01 | On a machine with no browser, the developer runs `keeplane login --server https://keeplane.kind.test`, approves the code from another browser on Keeplane's device pages, then runs `keeplane whoami`. | The first line is `No browser can open here, so sign in from another device.`, then `Open https://keeplane.kind.test/oauth/confirm-device/ and enter code <code>.`; after approval `Signed in to Keeplane.`, exit 0, and `whoami` names the developer. The saved sign-in is the device client's, for `https://keeplane.kind.test`, with the gateway address the server gave: `https://keeplane.kind.test/v1`. |
| KDEV-02 | In the sample repo they run `keeplane models`, then `keeplane code --model <shared-key model> "Say hello"` with no `--gateway`. One request with their sign-in, and one without, go straight to `https://keeplane.kind.test/v1/chat/completions`. | `models` exits 0 and lists both models. The task exits 0, shows "mock cloud answer" and `Answered by <model>.`; the fixture answered the shared key at least once. The request with the sign-in answers 200 with "mock cloud answer"; the one without is refused with 401 or 403 and no answer. The fixture's record holds no key. |
| KDEV-03 | The developer saves a new key for the own-key model with `keeplane keys set --model <model> --key-stdin` (the provider accepts it), then runs `keeplane code --model <model> "Say hello"`. | Before, `keys list` shows the model needs their own key and it is `missing`; `set` exits 0 with `added`. The task exits 0, shows "mock cloud answer" and `Answered by <model>.` Every answer the fixture gave during the task was to that key, by its hash: the shared key and no other key were sent, and the fixture refused nothing. The runtime keeps no provider sign-in of its own in the developer's home, before or after. `keys list` still shows `added`. Neither the fixture's record nor the CLI's output holds the key. |
| KDEV-04 | The second developer signs in the same way and saves a new key for the own-key model. Then the provider refuses that key, as when it is revoked, and they run `keeplane code --model <model> "Say hello"` in their clone, then `keeplane keys list`. | Sign-in exits 0 with the code approved; before, the key is `missing`, and `set` exits 0 with `added`. The task exits 1 and says "The provider refused your own key for <model>, so this task stopped. Replace it with `keeplane keys set --model <model>`. Run `keeplane keys list` to see your keys." and not `Answered by`. `keys list` then shows the key as `refused`. The fixture saw that key only refused, never accepted, and neither its record nor the CLI's output holds the key. |

These cases run one ingress controller on one node, with kindnet, which
doesn't enforce NetworkPolicy, so the chart's network policies are off here;
the [isolated-network cases](kubernetes-isolated-cases.md) cover them with
the SQLite trial. The provider is a fixture, not a real provider, and the
account database is a single disposable server.

The report, `kind-protected.json`, records each case's observations without
any credential, under `test-results/` (not kept in Git).
