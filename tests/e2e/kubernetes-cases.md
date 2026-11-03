# Local Kubernetes integration cases

Run `test_local.py` against port 13000 first, then `test_kind.py`. The replica
tests use `second-local`; `test_kind.py` registers it through Keeplane when it is
absent (`test_local.py` removes the setups it added). The **Kubernetes live
checks** CI workflow runs both, then `test_gateway_secret_rotation.py`,
`test_existing_gateway_preflight.py` and `test_gateway_down.py`, on a kind
cluster for every pull request (see [Tests](../README.md)). Between
`test_kind.py` and the gateway key rotation it runs `test_gateway_copy_stops.py`
(K8S-18 to K8S-23), which stops gateway copies once both are ready again. K8S-START-01 and
K8S-14 to K8S-16 run in the unit and integration checks. `test_kind.py` deletes one gateway
pod in the **kind-keeplane** cluster; `test_gateway_copy_stops.py` deletes one and
later scales the gateway copies (StatefulSet) to one and back to two. Both
refuse any other Kubernetes context.
The managed kind preview and the customer-run gateway app require first-admin
sign-in; the test helpers use the local password file and never print its value.
The account cases in `accounts-cases.md` also run against port 13000 using
`KEEPLANE_BASE_URL`. The existing-gateway app is accessed only through a
short-lived loopback port-forward on port 13001 during its tests.
K8S-10–13 exercise the live existing-gateway install hook in kind. K8S-14–16
use simulated gateway replies to cover retry and refusal paths without changing
the supplied gateway.

| ID | What to do | Expected result |
| --- | --- | --- |
| K8S-START-01 | Start local setup with a required tool missing, an unsupported Node.js version or Docker unavailable. | A short prerequisite error stops setup before credentials, dependency installation, builds or cluster changes. The unit startup controls use isolated command stubs. |
| K8S-01 | Install Keeplane with its managed gateway and inspect the gateway copies (StatefulSet) pods. | Two gateway copy pods are running and ready. |
| K8S-02 | Register `second-local` through Keeplane, then request the model list from each gateway copy directly without a key and with the app's runtime key. | Both copies refuse the anonymous request and list `second-local` only for the app key; registration is shared. |
| K8S-03 | Delete one gateway pod, observe the Service remove it as a ready endpoint, then send ten new questions to `second-local`. | All ten return the fixed answer. A call aimed at the stopped pod during endpoint propagation, including an active stream, may fail visibly and be retried. |
| K8S-04 | Wait for the gateway copies (StatefulSet) to recover. | Two copies are ready again. |
| K8S-18 | From the app pod, start a streamed reply from `local-fixture` through gateway copy 0's own address, with the prompt that makes the fixture model send 40 chunks a quarter of a second apart. After two chunks arrive, delete copy 0's pod with a one-second grace period. | The reply stops before its end: no chunk with a finish reason and no `[DONE]` arrive, and the text is incomplete. The stream may close without an error (on the first CI run it closed normally about 3 seconds after the stop, after 14 of 40 chunks), so the caller sees the failure by the missing final chunk and `[DONE]`; a reset or a timeout also passes. |
| K8S-19 | Once the gateway Service no longer offers the stopped pod, send the same streamed request again to the surviving copy's own address and then through the gateway Service. | Both retries stream the whole reply, with its finish reason and `[DONE]`. |
| K8S-20 | Scale the gateway copies to one while the app still lists two, then add `copy-down-add` (fixture, one data class). | HTTP 503 with "copy-down-add wasn't added" / "Not every gateway copy confirmed it: 1 of 2 did. Nothing was saved. Check the gateway and try again." The model is not in Keeplane's model list or the gateway's. |
| K8S-21 | With one copy still down, widen `copy-check` (added while both copies ran, with one data class) to two data classes. | HTTP 503 with "copy-check wasn't changed" / "Not every gateway copy confirmed the change: 1 of 2 did. Nothing was saved, and its earlier setup stays. Check the gateway and try again." It keeps its one class. |
| K8S-22 | With one copy still down, withdraw every data class from `copy-check`. | Saved at once: HTTP 200 in less than the copy readback's 5 seconds, and the model now has no classes. |
| K8S-23 | Scale the gateway copies back to two, wait until both are ready, then add `copy-down-add` and widen `copy-check` again. | Both are saved (HTTP 200) with the classes asked for. The test then removes both models and turns data classes off again if it turned them on. |
| K8S-05 | Install Keeplane in existing-gateway mode against a separately installed agentgateway; sign in, set up `customer-managed` through Keeplane, and ask it a question. | Keeplane's namespace contains its app Deployment, Service and local trial PVCs but no gateway Deployment. The app points to the supplied gateway, registers and approves the model there, and returns the fixture answer. |
| K8S-17 | Ask the existing-gateway app for models anonymously, then sign in as the first admin and open Users, Data Classes and Audit APIs. | The anonymous request is refused; the protected account and admin APIs work through the customer-run gateway installation. |
| K8S-06 | Compare the supplied gateway's model catalog with Keeplane's managed gateway catalog using the app key, and try both without a key. | Anonymous lists are refused. The supplied gateway keeps its pre-existing `customer-fixture` and gains `customer-managed`; neither appears in the managed gateway. The managed gateway's `second-local` does not appear in the supplied gateway. Both are Ready. |
| K8S-07 | After the managed gateway has recovered from pod replacement, register `second-local` again five times with the same settings. | Every registration is idempotent and returns HTTP 200; no management API error occurs. |
| K8S-08 | Install a temporary Keeplane app against a working supplied gateway, then simulate that gateway becoming unreachable. Inspect its Deployment and Service. | The app stays Ready and its Service has an endpoint, so the admin UI remains reachable. |
| K8S-10 | Install the existing-gateway mode against the supplied gateway with a known fixture model; run the same check inside the app pod. | The Helm pre-install or pre-upgrade hook succeeds only after the pinned version, model-list API, model-management read API and fixture inference answer; the app's direct probe passes. |
| K8S-11 | Run the existing-gateway check with a deliberately wrong expected version. | It fails before any gateway change. |
| K8S-12 | Run the check with a model absent from the supplied gateway. | It fails before any gateway change. |
| K8S-13 | Try a fresh existing-gateway install in a temporary namespace with the wrong expected gateway version. | Helm refuses the install before creating a Keeplane app Deployment. |
| K8S-14 | Make each model-list and management read fail once, then return a valid answer. | The read-only preflight retries each once and accepts the compatible gateway without changing its configuration. |
| K8S-15 | Keep the model-management read unavailable after the retry. | Preflight refuses the install; it does not infer compatibility from the model list alone. |
| K8S-16 | Refuse the model-management read with HTTP 401. | Preflight refuses immediately and does not retry an authorization failure. |
| K8S-09 | Sign in through the temporary Service with CSRF protection, then request the React Models application, app readiness, dependency health and model list. | Sign-in, the application bundle and app readiness answer 200; dependency health and the authenticated model list report 503. MO-UI-04 checks the visible gateway warning and Try again control in the browser. |
| K8S-UI-01 | Open the temporary gateway-down app in a browser after the page loads. | The gateway warning and Try again are visible, Add model is disabled, and the table says Models unavailable. |
| MGMT-01 | Replay the observed gateway management read returning HTTP 500 once, then HTTP 200. | Keeplane retries only the read and returns the successful model list. |
| MGMT-02 | Replay a gateway management read that keeps returning HTTP 500. | Keeplane stops after three reads and reports the failure; it does not retry a write. |
| MGMT-03 | Replay one timed-out model-configuration read followed by a successful read. | Each read is limited to ten seconds; Keeplane retries the read and returns the model list. |

These cases test local transport, shared registration, a pod failure and a
separate supplied gateway. The supplied gateway is an independently installed
upstream chart with its own disposable PostgreSQL in the same kind cluster,
not an actual customer's installation.
The cases do not prove behavior when a Kubernetes node or PostgreSQL fails, or
an external model endpoint is used. K8S-18 stops a copy with a short grace
period; a copy that stops without any (a node lost) is not tried. K8S-20 to
K8S-23 take the copy away by scaling the gateway copies down, so its address no
longer resolves; a copy that answers but reads back another state is covered
only by the unit checks of the copy readback.
