# Choose where the model gateway runs

Keeplane's Kubernetes integration trial has two installation modes. The mode
is set when installing Keeplane, not on the Models and routing page. The page
is the same in either mode. A **local model runner** is a separate choice: it
serves a model behind whichever gateway the installation uses. Here
`managed` means Keeplane installs the gateway inside the customer's cluster;
it does not mean a Keeplane-hosted cloud service. The hosted service is outside
the current release scope.

| Mode | Keeplane installs | Gateway address | Current trial |
| --- | --- | --- | --- |
| `managed` | Keeplane app and gateway | The chart's gateway Service | Two agentgateway copies (`gateway.copies`) with shared PostgreSQL registration |
| `existing` | Keeplane app only | `gateway.url`, supplied by the operator | A separate agentgateway installation in another namespace |

In `managed` mode the chart always requires keys on the gateway's model and
management port and refuses to install without `gateway.keysSecret`; see
[gateway access keys](kubernetes-installation-reference.md#gateway-access-keys).
In `existing` mode the customer-run gateway keeps its own key setup. To change
the keys later, see [rotate the gateway keys](#rotate-the-gateway-keys).

When the gateway runs as several copies, the app needs every copy's own
management address in `GATEWAY_COPY_URLS`. A model change that adds or widens
access is then confirmed only when every copy reads it back within 5 seconds;
withdrawals apply at once. If any entry is invalid, the app logs a warning and
refuses every change that adds or widens access, telling the admin to ask
whoever installed Keeplane to fix the list. See
[every gateway copy](../architecture/model-registration.md#every-gateway-copy).

- **`managed`:** the chart sets the list. It runs `gateway.copies` gateway
  copies (default 2) with stable private addresses,
  `http://<release>-gateway-<N>.<release>-gateway-copies.<namespace>.svc:4000`,
  and gives the app exactly those addresses.
- **`existing`:** list each copy's own management origin in
  `gateway.copyUrls`, for example
  `http://gateway-0.gateway.ai-gateway.svc:4000`. Helm refuses an entry with
  credentials, a path or another scheme, a repeated entry, or more than 32.
  Leave it empty for a gateway that runs as one copy.

See [gateway copies](kubernetes-installation-reference.md#gateway-copies) for
the values and what Helm refuses.

## Try both modes locally

Follow [the kind setup](kubernetes-local.md) to start the isolated trial. It
installs managed Keeplane in `keeplane` and a protected Keeplane app in
`keeplane-existing`. Inspect what actually runs:

```sh
kubectl --kubeconfig /private/tmp/keeplane-kind-kubeconfig -n keeplane get deploy,sts,svc
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
stays available. The [versioned run](https://github.com/OsamaFelFel/keeplane/blob/6cf7bfc2a3defce262a2da1fe526a2d37fe33cc6/tests/e2e/runs/2026-10-09-existing-preflight.md)
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
To repeat the React browser suite through a temporary port-forward:

```sh
.venv/bin/python -m pytest tests/e2e/test_existing_gateway_browser.py -m live
```

Shared cloud-provider keys are not proven in this mode: the supplied gateway
runs in a different namespace and cannot read Keeplane's private provider-key
PVC. The local app rejects shared-key registration before saving the key or
changing the gateway, with an explicit error. The release gateway contract
needs a supported secret-delivery mechanism for customer-run gateways before
this mode handles shared or personal keys.

## Keeplane's checks on a customer-run gateway

A customer-run gateway asks Keeplane before each model call. Point both checks
at the Keeplane app over the private network, with the developer's session as
the Bearer credential and the private gateway credential in
`X-Keeplane-Gateway-Credential`
([contract](../architecture/runtime-authorization.md)):

| Where on the gateway | Keeplane check | Writes an Audit record |
| --- | --- | --- |
| The route that carries developer model traffic | `POST /internal/runtime/authorize` | Never |
| Each model backend, after the gateway picks the model | `POST /internal/runtime/authorize/selected` | One per request sent, when **Model answers** is on |

Both send only `project_id` and `model_id`, never the prompt. A gateway that
calls only the first check still protects the model, but writes no
**Model answers** records. The backend check runs again for each retry, so a
retried request is recorded once per try, as on the managed gateway. A managed
install refuses the backend check: its own gateway records instead.

## Retry a model that is down

When a model answers with a 5xx, times out, or answers 429 before its first
byte, the gateway retries the same model twice, then returns the error. The
developer's CLI then lists the other allowed models; Keeplane never switches the
model itself. Never retry after the first byte of a streamed answer.

| Where | Who sets it |
| --- | --- |
| Docker preview, managed runtime profile | The Keeplane runtime installer adds it to the protected `keeplane-chat` route. |
| Kubernetes chart, `managed` | Not yet: the chart does not install the protected listener. The retry arrives with it. |
| Customer-run gateway, `existing` | The operator, on the route that carries developer model traffic. |

On a customer-run agentgateway, attach this native policy to that route,
next to its entry authorization:

```yaml
policies:
  retry:
    attempts: 2          # retries after the first try: three tries at most
    codes: [429, 500, 501, 502, 503, 504, 505, …, 599]   # 429 and every 5xx, listed
    backoff: 500ms
  timeout:
    backendRequestTimeout: 60s   # per try, up to the response headers
```

Keep the selected-model authorization (`/internal/runtime/authorize/selected`)
on each model backend, not only on the route, so every retry is checked again. Do not add a failover group or virtual
model for an outage: that would switch the model. List every code from 500 to 599: the
policy takes exact codes, not a range. A provider that refuses the connection is
retried natively. Leave 4xx codes other than 429 out of `codes`; a context-length refusal must reach the developer at once.
Another gateway product needs the same behaviour with its own settings.

## Rotate the gateway keys

Keeplane holds two gateway keys in `gateway.keysSecret`: `admin-key` for
model management and `runtime-key` for model calls. The app reads both key
files again for every gateway call, so it picks up new keys without a restart
once Kubernetes refreshes the mounted Secret (usually within a minute or two).
Changing keys never touches the gateway's model store: Keeplane's models, your
own models and Keeplane's approvals, which are tied to each model's
definition, stay exactly as they were
([CR-01](../../tests/integration/credential-rotation-cases.md)).

Use `check_credentials` before and after, and compare the model and approval
lists, as described in
[before and after every rotation](postgres-accounts.md#before-and-after-every-rotation),
which also sets the `NS`, `RELEASE` and `mounted_sha` used below. It shows each gateway copy's answer to each key: `accepted`, `refused`,
`unreachable`, or `unreadable` for a missing key file. While a copy refuses
Keeplane's admin key, the admin status API answers 503 "The gateway refused
Keeplane's admin key…" and the app logs the same line
([CR-02](../../tests/integration/credential-rotation-cases.md)).

Pick a quiet time and don't add, change or remove models until the rotation is
finished: a model change is confirmed only when every copy reads it back, and
a copy that refuses the key leaves it unconfirmed.

### Managed gateway

The gateway copies load `runtime-key-hash` and `admin-key-hash` when they
start, and the chart allows exactly one hash per key policy. So the old and new
keys can't both be accepted: between the Secret change and the end of the
restart, some gateway calls are refused with 401. Keep that window short by
running steps 2 and 3 back to back.

1. Make new keys and hashes, as at installation:

   ```sh
   umask 077
   openssl rand -base64 32 | tr -d '\n' > runtime-key
   openssl rand -base64 32 | tr -d '\n' > admin-key
   for name in runtime admin; do
     printf 'sha256:%s' "$(shasum -a 256 < $name-key | cut -d ' ' -f 1)" > $name-key-hash
   done
   ```

2. Replace the Secret's four keys, keeping its name:

   ```sh
   kubectl -n "$NS" create secret generic <keys-secret> \
     --from-file=runtime-key --from-file=admin-key \
     --from-file=runtime-key-hash --from-file=admin-key-hash \
     --dry-run=client -o yaml | kubectl -n "$NS" apply -f -
   ```

3. Restart the gateway copies so they load the new hashes. They restart one at
   a time, highest number first:

   ```sh
   kubectl -n "$NS" rollout restart statefulset/"$RELEASE"-gateway
   kubectl -n "$NS" rollout status statefulset/"$RELEASE"-gateway
   ```

4. Run `check_credentials` until every copy shows `"admin_key": "accepted"` and
   `"runtime_key": "accepted"`, usually within two minutes, then save
   `after.json` and compare the lists: same models, same fingerprints, same
   approvals.

During steps 2 to 4, developers' model calls and admin model pages may fail
and `/health` answers 503. A call a copy has already accepted carries on until
that copy stops; the copy's 30-second shutdown cuts anything longer, and the
developer sends it again.

If something goes wrong:

- **A copy still refuses after its restart.** Its hash doesn't match the key,
  often because a hash was made from a file with a trailing newline. Make the
  hashes again from step 1's files and repeat steps 2 and 3.
- **The copies accept but an app pod is still refused after a few minutes.**
  That pod hasn't received the new files yet; restart the app with
  `kubectl -n "$NS" rollout restart deployment/"$RELEASE"-app`.
- **To go back**, apply the previous four files the same way and restart the
  copies again.

### Customer-run gateway

Your gateway decides which keys it accepts, and Keeplane only holds
`runtime-key` and `admin-key` (no hashes). If your gateway accepts several
keys per policy, as agentgateway's `apiKey` key list does, rotate with no
refused calls:

1. Add the new keys to your gateway next to the old ones, keeping the same
   separation: the admin key manages Keeplane's models, the runtime key lists
   and calls models.
2. Replace Keeplane's two keys in the Secret:

   ```sh
   kubectl -n "$NS" create secret generic <keys-secret> \
     --from-file=runtime-key --from-file=admin-key \
     --dry-run=client -o yaml | kubectl -n "$NS" apply -f -
   ```

3. Wait until every app pod reads the new files. Both keys still work, so
   compare file hashes rather than relying on the check:

   ```sh
   for pod in $(kubectl -n "$NS" get pods -l app="$RELEASE"-app -o name); do
     echo "$pod $(mounted_sha "$pod" /run/gateway-keys/admin-key) $(mounted_sha "$pod" /run/gateway-keys/runtime-key)"
   done
   tr -d '\n' < admin-key | shasum -a 256; tr -d '\n' < runtime-key | shasum -a 256
   ```

4. Remove the old keys from your gateway, run `check_credentials` until it
   passes, and compare the lists with `before.json`.

If your gateway accepts only one key per policy, change it and the Secret back
to back, as for the managed gateway, and expect refused calls until both are
done. The next `helm upgrade` runs the compatibility preflight with the keys
then in the Secret. The private credential your gateway sends to Keeplane's
checks (`X-Keeplane-Gateway-Credential`) is configured outside this chart.

## Release configuration plan

The release gateway has not been selected. The agentgateway v1.6.0 chart is
only the current integration trial. Before exposing the two modes as a release
contract, we need to:

1. Select a gateway artifact that passes the license and capability checks.
   Record its supported versions in the
   [component manifest](../architecture/component-manifest.md).
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
