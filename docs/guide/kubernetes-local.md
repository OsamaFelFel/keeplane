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
For another managed-app port, use the same port-forward pattern with namespace
`keeplane`, `service/keeplane-app` and a free host port. This avoids recreating
the cluster and its volumes.

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
- **Port-forward fails:** check that the existing app pod is ready and the host
  port is free. Change the first port number if needed.
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

## Keep data and understand the limits

Rerunning setup preserves the app's PVC-backed records and existing credential
files. Keep the files under `/private/tmp/keeplane-accounts-trial/`; recovering
a missing gateway database password needs the
[database credential guide](gateway-database-secret.md). Deleting the kind
cluster deletes its local volumes. The gateway databases use temporary storage:
replacing their database pods loses their catalogs unless you back up first.

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
