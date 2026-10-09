# Choose where the model gateway runs

Keeplane's Kubernetes integration trial has two installation modes. The mode
is set when installing Keeplane, not on the Models and routing page. The page
is the same in either mode. A **local model runner** is a separate choice: it
serves a model behind whichever gateway the installation uses. Here
`managed` means Keeplane installs the gateway inside the customer's cluster;
it does not mean a Keeplane-hosted cloud service. The hosted service is outside
the current Open Source release scope.

| Mode | Keeplane installs | Gateway address | Current trial |
| --- | --- | --- | --- |
| `managed` | Keeplane app and gateway | The chart's gateway Service | Two agentgateway replicas with shared PostgreSQL registration |
| `existing` | Keeplane app only | `gateway.url`, supplied by the operator | A separate agentgateway installation in another namespace |

## Try both modes locally

Follow [the kind setup](kubernetes-local.md) to start the isolated trial. It
installs managed Keeplane in `keeplane` and app-only Keeplane in
`keeplane-existing`. Inspect what actually runs:

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane get deploy,svc
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane-existing get deploy,svc
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n supplied-gateway get deploy,svc
```

The example app-only Helm settings are:

```sh
helm upgrade --install keeplane-existing deploy/helm/keeplane \
  --kubeconfig /private/tmp/keeplane-kind-kubeconfig \
  --namespace keeplane-existing \
  --set gateway.mode=existing \
  --set gateway.install=false \
  --set gateway.url=http://supplied-gateway.supplied-gateway.svc.cluster.local:4000 \
  --set gateway.expectedVersion=1.6.0 \
  --set gateway.preflightModel=customer-fixture \
  --set app.runnerUrls=http://model.supplied-gateway.svc.cluster.local:18080 \
  --set app.image=keeplane-preview:kind-local \
  --set app.pullPolicy=Never
```

The app-only install registers new models through the supplied gateway's
management API; it must have permission to change Keeplane-managed models.
In this local trial, a Helm pre-install or pre-upgrade job checks the pinned
gateway version, model listing, and management read API before installing the
app. When `gateway.preflightModel` is set, it also makes one small inference
call through that registered model. A wrong version or absent model blocks a
fresh install before the app Deployment is created. The probe does not change
gateway configuration; a non-fixture model may charge for the inference call.
The [K8S-10–13 cases](../../tests/e2e/kubernetes-cases.md) record a passing
install and deliberately refused inputs. The [gateway-outage case](../../tests/e2e/kubernetes-cases.md)
starts with a valid install, then simulates an outage and confirms the app UI
stays available. The [versioned run](../../tests/e2e/runs/2026-10-09-existing-preflight.md)
includes the final full regression and the corrected rollout test.
The trial's `app.runnerUrls` setting allows the Add model form to reach a
specified local runner while the preview has no admin sign-in; it is separate
from `gateway.url`. A release installation needs authenticated admins and
runner address controls before accepting arbitrary network addresses.
The `K8S-05` and `K8S-06` cases check registration, a model call and separation
from the managed gateway's catalog. An existing model that the customer added
outside Keeplane must remain untouched and receive no Keeplane work until an
admin approves its key choice and data classes. The protected Docker preview
now enforces that approval and preserves an outside model's gateway
registration when its Keeplane setup is removed. The app-only kind preview has
not yet been wired to the protected account service, so this policy has not
been tested end to end in existing-gateway mode.

## Release configuration plan

The release gateway has not been selected. The agentgateway v1.6.0 chart is
only the current integration trial. Before exposing the two modes as a release
contract, we need to:

1. Select a gateway artifact that passes the license and capability checks.
   Record its supported versions in the compatibility manifest.
2. Extend the local existing-gateway preflight for the selected release gateway:
   check registration permission, TLS and authentication, and fail before
   changing the customer's gateway if any check fails. The current trial checks
   the version and read APIs; its inference check is enabled when an operator
   supplies a known model. It does not prove management write permission.
3. Carry the protected preview's model ownership and approval rules into both
   Kubernetes modes. Preserve unrelated gateway models and settings.
4. Supply production PostgreSQL and secret configuration for `managed`, then
   repeat the full regression suite in both modes on each supported version.

These mode settings choose the **gateway deployment**. They do not choose a
model. After installation, an admin adds an external endpoint or a local
runner's address through Keeplane's Models and routing flow.
