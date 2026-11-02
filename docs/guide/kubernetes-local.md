# Run Keeplane locally on Kubernetes

Use this development environment to try Keeplane with a gateway it installs,
and with a gateway installed separately. It uses a kind cluster named `keeplane`.
Production installation and recovery remain in progress.

## Before you start

- Install Python 3.9 or later, Node.js 22.12 or later with npm, Docker, kind,
  kubectl, Helm and ripgrep (`rg`). Keep Docker running.
- Start [the Docker preview](local-preview.md) once. Its launcher downloads the
  pinned Qwen demo file into `models/`; the Kubernetes setup requires that file.
- Allow internet access for initial image and dependency downloads, and leave
  ports 13000 and 13001 free. Docker uses its own configured port.

Run from the repository root:

```sh
deploy/local/kind-up.sh
```

The script builds the UI and app, loads images into kind, and starts the models
and gateways. It checks tools, Node.js and Docker before creating credentials or
building. Run it again after changing the app or chart. It uses
`/private/tmp/keeplane-kind-kubeconfig` rather than your default Kubernetes
context. Set `KEEPLANE_KUBECONFIG` to use another kubeconfig file, or
`KEEPLANE_HELM_BIN` if Helm is outside `PATH`.

## Know which component set you install

Keeplane has not been released, so no version is supported yet. The setup
installs the component set that your checkout's
[component manifest](../architecture/component-manifest.md) describes: the
Keeplane chart, the app image built from your checkout, the agentgateway trial
chart and image, package versions, migrations and default features. The
gateway entry is an integration trial, not the release gateway.

To see the main entries, run from the repository root:

```sh
python3 -c 'import json; m = json.load(open("deploy/component-manifest.json")); print(m["release_status"], m["chart"]["version"], m["gateway"]["status"], m["gateway"]["runtime_version"])'
```

Expected result: `pre-release 0.1.0 integration-trial 1.6.0`, or the newer
values in your checkout.

In Git, the manifest's `build` fields stay empty: commit and digests are known
only after a build. Each run of the **Build and application checks** workflow on
GitHub builds the app image, packages the chart and keeps a filled-in copy. To
find the copy for the commit you are installing:

1. Open the repository's **Actions** tab, then the **Build and application
   checks** run for that commit.
2. The run summary shows **Component manifest for this build**, with the commit,
   app image ID and chart package digest.
3. Download the `component-manifest-<commit>` artifact. It holds
   `component-manifest.json` and the chart package `keeplane-<version>.tgz`.

With the GitHub CLI signed in, the same steps are:

```sh
commit="$(git rev-parse HEAD)"
gh run list --repo OsamaFelFel/keeplane --workflow checks.yml --commit "$commit"
gh run download <run-id> --repo OsamaFelFel/keeplane \
  --name "component-manifest-$commit" --dir test-results/ci-manifest
```

Then check the copy against your checkout and the downloaded chart package:

```sh
copy=test-results/ci-manifest/component-manifest.json
image="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["build"]["app_image_digest"])' "$copy")"
python3 deploy/stamp_component_manifest.py --commit "$commit" --app-image "$image" \
  --chart-package test-results/ci-manifest/keeplane-*.tgz --check "$copy"
```

Expected result: `... matches commit <your commit>, image sha256:..., chart
sha256:...`. The check confirms the commit, recomputes the chart package digest
and confirms that every other entry equals your checkout's manifest. The app
image ID names the image built in that run; no registry image is published, so
the check takes it from the copy, and your own local build has a different ID.

To record the set you installed locally, run this after `kind-up.sh`. The output
path is ignored by Git:

```sh
python3 deploy/stamp_component_manifest.py --commit "$(git rev-parse HEAD)" \
  --app-image-from-docker keeplane-preview:kind-local \
  --output test-results/installed-component-manifest.json
```

If something does not match:

- **No run or artifact for your commit:** pushes to `main` and pull requests
  run the workflow; documentation-only pull requests skip the build. For a pull
  request, the run builds GitHub's test merge commit, which is the commit in the
  artifact name. Artifacts are kept for 30 days; after that, record your own
  build as above.
- **`Docker has no built image`:** run `deploy/local/kind-up.sh` first, then
  retry.
- **`... is not stamped` or `... but this build produced ...` from `--check`:**
  the copy belongs to another build. Download the artifact for your commit.

## Open Keeplane

| Installation | Browser address | What runs |
| --- | --- | --- |
| Managed gateway | [127.0.0.1:13000](http://127.0.0.1:13000) | Keeplane in `keeplane`, two gateway copies and their database |
| Existing gateway | [127.0.0.1:13001](http://127.0.0.1:13001), after port-forwarding | Keeplane in `keeplane-existing`, using the gateway in `supplied-gateway` |

Sign in as `first-admin`. The Kubernetes password file is
`/private/tmp/keeplane-accounts-trial/first-admin-password`. Docker's launcher
prints its own credential path; do not assume the passwords match. The
installations keep separate accounts, settings and model approvals.

For the existing-gateway installation, keep this command running in another
terminal, then open port 13001:

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane-existing \
  port-forward service/keeplane-existing-app 13001:3000 --address 127.0.0.1
```

Close that command when finished. These loopback addresses are accessible from
your own computer. The managed port 13000 comes from
[`deploy/local/kind.yaml`](../../deploy/local/kind.yaml); the existing app's
browser port is the first number in `13001:3000` above.
To use another port, follow [Change the browser port](#change-the-browser-port)
below. The app must also trust the new browser address for sign-in and changes.

In **Models and routing**, choose **Add model** → **Local runner**:

| Installation | Runner address | Model |
| --- | --- | --- |
| Managed | `http://qwen:8080` | `qwen2.5-coder:0.5b`, a real small model |
| Existing | `http://model.supplied-gateway.svc.cluster.local:18080` | `mock-local`, a fixed test answer |

Choose **Find models**, select the model and add it. If its row already exists,
use **Set up**. When data classes are enabled, choose its approved classes too.
Runner addresses are internal to the cluster, so enter them in Keeplane rather
than opening them in your browser. See [model setup](model-add-local.md).

## Inspect and troubleshoot

Use the isolated kubeconfig for every command. If you changed its path, replace
it in these examples:

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane get pods,deploy,svc
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane-existing get pods
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n supplied-gateway get pods,deploy,svc
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane logs deployment/keeplane-app --tail=100
```

- **Missing model:** run the Docker launcher to obtain the pinned file.
- **Checksum mismatch:** move the reported model file aside, then run the Docker
  launcher to download it again. Both launchers refuse a different file.
- **Port-forward fails:** check that the app pod is ready and the host port is
  free. Follow the port-change steps below if you need another port.
- **Gateway unavailable:** inspect its pods and logs. Keeplane's UI remains
  available to show the gateway warning; `/health` reports dependency health.
- **Raw gateway UI returns 401:** gateway management requires its private admin
  key. Use Keeplane's Models and routing screen for normal model management.

To run Kubernetes application checks, prepare the Python environment in
[Testing](regression-local.md), then choose a new result path:

```sh
.venv/bin/python tests/run_regression.py --group kind \
  --output test-results/kind-review.json
```

This runs the kind application group. Chart, network and deployment checks have
separate groups in the testing guide. Reusable procedures live in
[Kubernetes cases](../../tests/e2e/kubernetes-cases.md).

## Change the browser port

Port-forwarding changes how the browser reaches Keeplane. The app also checks
the browser's origin (scheme, host and port) before accepting sign-in or changes.
Changing only the port-forward can load the page but leave those actions blocked.

For example, to add port 14000 to the managed trial, first update its trusted
addresses. This preserves the default addresses and the installed release's
other values, including its image and Secret names. If you already added custom
aliases, include them in the comma-separated list too.

```sh
helm upgrade keeplane deploy/helm/keeplane \
  --kubeconfig /private/tmp/keeplane-kind-kubeconfig --namespace keeplane \
  --reuse-values \
  --set-string app.localTrial.publicOrigin=http://127.0.0.1:14000 \
  --set-string 'app.localTrial.publicOriginAliases=http://127.0.0.1:13000\,http://localhost:13000\,http://localhost:14000' \
  --wait
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane \
  port-forward service/keeplane-app 14000:3000 --address 127.0.0.1
```

Keep the second command running and open <http://127.0.0.1:14000>. For the
existing-gateway trial, replace the release and namespace with
`keeplane-existing`, the Service with `keeplane-existing-app`, and the original
port 13000 with 13001 in the alias list. Choose a different free port if needed.
The backslashes inside the quoted alias value let Helm accept the commas.

These settings become `PUBLIC_ORIGIN` and `PUBLIC_ORIGIN_ALIASES` in the app.
Aliases are explicit addresses, without paths or trailing slashes. No cluster
recreation is needed. Closing the port-forward leaves the trusted addresses in
place; rerunning `kind-up.sh` restores the checked-in local values. Keep a local
values override if you want to reapply your addresses after setup.

## Keep data and understand the limits

Rerunning setup preserves the app's PVC-backed records and existing credential
files. Earlier preview files on the state claim (`accounts.sqlite3` and
`model-approvals.sqlite3`) aren't imported: before the first release Keeplane
doesn't carry an earlier preview's data forward. Keep the files under `/private/tmp/keeplane-accounts-trial/`; recovering
a missing gateway database password needs the
[database credential guide](gateway-database-secret.md). Deleting the kind
cluster deletes its local volumes. The gateway databases use temporary storage:
replacing their database pods loses their catalogs unless you back up first.

App startup repairs the provider-key volume's ownership and private permissions
without moving or replacing keys. Its short init container runs as UID 0, mounts
only that volume, and is not privileged. Clusters enforcing the Restricted Pod
Security profile need an explicit exception for this initializer. Managed gateway
pods must leave `fsGroup` unset so their restarts do not widen key permissions.
Upgrade the app and gateway together; an older app image lacks the initializer.

The [stack lock](../../deploy/local/stack.lock.json) pins trial images, chart and
demo model. Local values are development inputs. The cluster's kindnet CNI does
not enforce NetworkPolicy; TLS Ingress and gateway ingress policies are optional
and disabled here. Production needs operated PostgreSQL, storage and Secret
recovery, enforced network controls, certificate operations and the completed
runtime policy and package review. See [gateway modes](gateway-configuration.md)
and [PostgreSQL configuration](postgres-accounts.md) before planning an install.

The supplied gateway cannot read Keeplane's provider-key volume in another
namespace, so shared-key registration is refused there. The bundled Qwen runner
has a 4,096-token active context and a 256-token output limit. Runner capacity and
request sampling are separate; the admin UI does not configure them.

### Preserve settings when upgrading Helm

`--reuse-values` can restore old chart defaults, including the gateway's
`fsGroup`. Save the release's explicit user settings privately, then apply them
to the new chart defaults with `--reset-values`:

Build and load the updated app image using the setup steps above; the old image
lacks the provider-volume initializer.

```sh
umask 077
values_dir="$(mktemp -d /tmp/keeplane-helm-values.XXXXXX)"
helm --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane \
  get values keeplane -o json > "$values_dir/original-values.json"
helm --kubeconfig /private/tmp/keeplane-kind-kubeconfig \
  upgrade keeplane deploy/helm/keeplane --namespace keeplane \
  --reset-values -f "$values_dir/original-values.json" \
  --set-json 'agentgateway-standalone.podSecurityContext.fsGroup=null' \
  --wait --timeout 180s
```

Export without `--all`; computed old defaults would reintroduce the problem.
For the existing-gateway app, replace both release and namespace with
`keeplane-existing`. Keep the export outside Git: values can contain private
configuration. Retain it if the upgrade fails, correct the reported error and
retry with that file. This export does not back up databases or provider keys.
