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
installs managed Keeplane in `keeplane` and a protected Keeplane app in
`keeplane-existing`. Inspect what actually runs:

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane get deploy,svc
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane-existing get deploy,svc
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n supplied-gateway get deploy,svc
```

The tested local settings are in `deploy/local/existing-values.yaml`. The kind
setup creates the first-admin and gateway-key Secrets in this namespace. To
reapply the existing-gateway app without installing another gateway:

```sh
helm upgrade --install keeplane-existing deploy/helm/keeplane \
  --kubeconfig /private/tmp/keeplane-kind-kubeconfig \
  --namespace keeplane-existing \
  -f deploy/local/existing-values.yaml --wait
```

For a temporary browser path, run the command below in another terminal and
open [the existing-gateway app](http://127.0.0.1:13001). Close the port-forward
when finished; the main Docker and managed kind previews stay on ports 3000
and 13000.

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane-existing \
  port-forward service/keeplane-existing-app 13001:3000 --address 127.0.0.1
```

The protected app registers new models through the supplied gateway's
management API; it must have permission to change Keeplane-managed models.
The local setup creates a `keeplane-gateway-keys` Secret in each trial
namespace. Its runtime key can list and call models but cannot read gateway
management; its admin key can manage models but cannot call them. The selected
customer gateway must support this separation and supply usable credentials
before installation. The sample Secret is only for the local fixture.
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
specified local runner; it is separate from `gateway.url`. The local app now
requires an admin session. A release still needs production identity and
runner address controls before accepting arbitrary network addresses.
The `K8S-05`, `K8S-17` and `K8S-06` cases check protected registration, a model call and separation
from the managed gateway's catalog. An existing model that the customer added
outside Keeplane must remain untouched and receive no Keeplane work until an
admin sets up its key choice and, if data classes are on, its class approvals.
The local customer-run gateway trial now refuses anonymous app calls, signs in
the first admin, sets up a no-key model and refuses work through an unrelated
unapproved model. Its account and browser cases are versioned under `tests/`.
Run the [plain-English existing-gateway cases](../../tests/e2e/existing-gateway-cases.md)
with the full regression command in [the regression guide](regression-local.md).
To repeat the React browser suite through a temporary port-forward, use a new
output filename:

```sh
python3 tests/e2e/test_existing_gateway_browser.py \
  --output tests/browser/runs/YYYY-MM-DD-existing-browser.json
```

Shared cloud-provider keys are not proven in this mode: the supplied gateway
runs in a different namespace and cannot read Keeplane's private provider-key
PVC. The release gateway contract needs a supported secret-delivery mechanism
for customer-run gateways before this mode handles shared or personal keys.

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
3. Carry the protected trial's model ownership and approval rules into both
   production modes, including shared and developer-owned key delivery.
   Preserve unrelated gateway models and settings.
4. Supply production PostgreSQL and secret configuration for `managed`, enforce
   the internal network boundary, then repeat the full regression suite in
   both modes on each supported version. The local key trial closes the tested
   credential-free calls, not project-class bypass or alternate routes.

These mode settings choose the **gateway deployment**. They do not choose a
model. After installation, an admin adds an external endpoint or a local
runner's address through Keeplane's Models and routing flow.
