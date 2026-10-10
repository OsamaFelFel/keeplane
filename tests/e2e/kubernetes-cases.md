# Local Kubernetes integration cases

Run `test_local.py` against port 13000 first. It registers `second-local`, which
the replica tests use. Then run `test_kind.py`. The latter deletes one gateway
pod in the **kind-keeplane** cluster and refuses any other Kubernetes context.
The managed kind preview requires first-admin sign-in; the test helpers use the
local password file and never print its value. The account cases in
`accounts-cases.md` also run against port 13000 using `KEEPLANE_BASE_URL`.
K8S-10–13 exercise the live existing-gateway install hook in kind. K8S-14–16
use simulated gateway replies to cover retry and refusal paths without changing
the supplied gateway.

| ID | What to do | Expected result |
| --- | --- | --- |
| K8S-01 | Install Keeplane with its managed gateway and inspect the gateway Deployment. | Two gateway copies are ready. |
| K8S-02 | Register `second-local` through Keeplane, then request the model list from each gateway copy directly. | Both copies list `second-local`; registration is shared. |
| K8S-03 | Delete one gateway pod and immediately send ten new questions to `second-local`. | All ten return the fixed answer. An already streaming reply from the deleted copy is allowed to fail visibly. |
| K8S-04 | Wait for the gateway Deployment to recover. | Two copies are ready again. |
| K8S-05 | Install Keeplane in existing-gateway mode against a separately installed agentgateway; inspect Keeplane's namespace, add `customer-managed` through Keeplane, and ask it a question. | Keeplane's namespace contains only its app Deployment and Service; the app points to the supplied gateway, registers the model there and returns the fixture answer. |
| K8S-06 | Compare the supplied gateway's model catalog with Keeplane's managed gateway catalog. | The supplied gateway keeps its pre-existing `customer-fixture` and gains `customer-managed`; neither appears in the managed gateway. The managed gateway's `second-local` does not appear in the supplied gateway. Both are Ready. |
| K8S-07 | After the managed gateway has recovered from pod replacement, register `second-local` again five times with the same settings. | Every registration is idempotent and returns HTTP 200; no management API error occurs. |
| K8S-08 | Install a temporary Keeplane app against a working supplied gateway, then simulate that gateway becoming unreachable. Inspect its Deployment and Service. | The app stays Ready and its Service has an endpoint, so the admin UI remains reachable. |
| K8S-10 | Install the existing-gateway mode against the supplied gateway with a known fixture model; run the same check inside the app pod. | The Helm pre-install or pre-upgrade hook succeeds only after the pinned version, model-list API, model-management read API and fixture inference answer; the app's direct probe passes. |
| K8S-11 | Run the existing-gateway check with a deliberately wrong expected version. | It fails before any gateway change. |
| K8S-12 | Run the check with a model absent from the supplied gateway. | It fails before any gateway change. |
| K8S-13 | Try a fresh existing-gateway install in a temporary namespace with the wrong expected gateway version. | Helm refuses the install before creating a Keeplane app Deployment. |
| K8S-14 | Make each model-list and management read fail once, then return a valid answer. | The read-only preflight retries each once and accepts the compatible gateway without changing its configuration. |
| K8S-15 | Keep the model-management read unavailable after the retry. | Preflight refuses the install; it does not infer compatibility from the model list alone. |
| K8S-16 | Refuse the model-management read with HTTP 401. | Preflight refuses immediately and does not retry an authorization failure. |
| K8S-09 | Through that temporary Service, request the admin page, app readiness, dependency health and model list. | The page and app readiness answer 200, while dependency health and the model list report 503. The page contains the gateway-unavailable notice and Try again control. |
| K8S-UI-01 | Open the temporary gateway-down app in a browser after the page loads. | The gateway warning and Try again are visible, Add model is disabled, and the table says Models unavailable. |
| MGMT-01 | Replay the observed gateway management read returning HTTP 500 once, then HTTP 200. | Keeplane retries only the read and returns the successful model list. |
| MGMT-02 | Replay a gateway management read that keeps returning HTTP 500. | Keeplane stops after three reads and reports the failure; it does not retry a write. |
| MGMT-03 | Replay one timed-out model-configuration read followed by a successful read. | Each read is limited to ten seconds; Keeplane retries the read and returns the model list. |

These cases test local transport, shared registration, a pod failure and a
separate supplied gateway. The supplied gateway is an independently installed
upstream chart with its own disposable PostgreSQL in the same kind cluster,
not an actual customer's installation.
The cases do not prove behavior when a Kubernetes node or PostgreSQL fails, a
stream is interrupted, or an external model endpoint is used.
