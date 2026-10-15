# Local model slice — test cases

These cases describe this running preview. They do not close Spec 002 or the later
accounts, routing and CLI specs.

| ID | What to do | Expected result |
| --- | --- | --- |
| LOCAL-01 | Sign in as the first admin and open Keeplane at `http://127.0.0.1:3000`. | The Models and routing screen and IBM Plex fonts load from the local app, and the gateway is connected. |
| LOCAL-02 | Inspect the model list. | `local-fixture` appears because the gateway loaded it from configuration and is clearly identified as a fixed answer fixture. |
| LOCAL-03 | Set up `local-fixture` when the protected Docker preview requires it, then ask a question. | An answer returns through Keeplane and the gateway. |
| LOCAL-04 | Register the fixed test fixture as `second-local` with upstream ID `mock-local` through the preview API; approve Public in the protected preview. | It appears in the list and answers a question through the gateway. |
| LOCAL-05 | Ask for a model that was not registered. | Keeplane or the gateway rejects the call; no answer is shown. |
| LOCAL-06 | Restart the gateway after adding `second-local`. | The registered model remains and still answers. |
| LOCAL-07 | Start the optional Qwen runner, register it from Keeplane, and ask a short coding question. | A generated answer comes through Keeplane and the gateway; the recorded model is `local-qwen`. |
| LOCAL-08 | Inspect the preview diagnostic API and a fixture's source. | The diagnostic API reports the running gateway version for compatibility checks; the admin UI does not show it. The fixture is identified as a fixed answer test source. |
| LOCAL-09 | Inspect `local-qwen` after a real model call. | Keeplane identifies it as a real local Qwen model served by llama.cpp, with the correct upstream model ID. |
| LOCAL-10 | Open Add model and compare the runner address and model dropdown with the design canvas. | The dialog is 560px wide at desktop size. Its input and dropdown controls share a 44px height. Keyboard focus is visible. |
| LOCAL-11 | Register an existing model again with the same settings, then try the same name with different settings. | The repeat is reported as already registered. The conflicting registration is rejected, and the existing model still answers. |
| LOCAL-12 | Call the guarded trial endpoint directly with no key and then with a wrong key. | Both calls are rejected with HTTP 401 before reaching Qwen. |
| LOCAL-13 | Add `guarded-qwen-e2e` using the guarded endpoint trial source and inspect the model list and gateway registry. | The gateway holds the endpoint and disposable test key. Keeplane lists the model as a guarded endpoint without returning the key to the UI. |
| LOCAL-14 | Ask `guarded-qwen-e2e` a question in Keeplane. | A generated answer returns through Keeplane, the gateway, and the guarded endpoint to the real Qwen runner. |
| LOCAL-15 | Register `guarded-qwen-e2e` again with the same settings, then try the same name with different settings. | The repeat is reported as existing. The conflict is rejected with HTTP 409. |
| LOCAL-17 | Open Add model and inspect the model list after guarded endpoint tests. | The dialog offers Local runner; the guarded credential-forwarding test is absent from the model list and provider selector. |
| LOCAL-18 | In the Kubernetes browser preview, find Qwen's served model at `http://qwen:8080`, add it, then send a coding prompt through the preview API. | The new model appears without a page reload, and a generated answer returns through Keeplane and the gateway. |
| LOCAL-21 | In Add model, give the enabled local runner address and choose Find models. | Keeplane lists the models served by that runner; it does not scan the network. |
| LOCAL-24 | Find the local Qwen model and inspect its context detail. | Keeplane reports the runner's effective 4,096-token context separately from the model's 32,768-token training context. |
| LOCAL-25 | Ask Keeplane to find a model on a local runner that lists models but has no `/props` endpoint. | Discovery succeeds and the optional context detail is absent; Keeplane does not reject an otherwise usable runner. |
| LOCAL-22 | Try an unavailable runner or an unknown model. | Keeplane reports why it could not add the model and saves nothing to the gateway. |
| LOCAL-23 | Inspect Models and routing, including while its gateway is unavailable. | No gateway product name or version and no Try panel appear. When unavailable, the exact product notice appears, Add model is disabled, and Try again checks the gateway. |
| LOCAL-19 | Read the running Qwen server's model details and defaults. | The pinned model reports a 4,096-token active context, a 32,768-token training context, and the expected temperature and top-p defaults. Record its reported default output limit separately. |
| LOCAL-20 | Ask the pinned Qwen runner, then `local-qwen` through agentgateway, to generate a list longer than 256 tokens without passing a request limit; suppress the model's end-of-sequence stop so the limit is reached. | Both paths stop at exactly 256 output tokens with a length finish reason. This checks the effective limit even if `/props` reports a different default. |

The local fixture returns a fixed answer. It proves transport and registration,
not model quality or compatibility with Claude or Codex. LOCAL-10 is a browser
inspection against the supplied design canvas and tokens; record its measured
dimensions with each UI change.

LOCAL-12–16 use a disposable container that checks a test key and forwards to
local Qwen. They prove gateway credential forwarding and a guarded endpoint
registration path. They do not prove external HTTPS, production secret storage,
real provider compatibility, or data-class enforcement.

LOCAL-16 was a historical browser trial of the guarded test route. It was
removed from the normal UI after it confused a user with an extra model choice.

## Local stack lock checks

Run `test_stack_lock.py` while both Docker and the isolated kind trial are up.
These cases compare [the pre-release component lock](../../deploy/local/stack.lock.json)
with the running installations.

| ID | What to do | Expected result |
| --- | --- | --- |
| LOCK-01 | Check the local Qwen model file and kind node image. | Their exact SHA-256 identities match the lock. |
| LOCK-02 | Inspect the Docker app, Qwen and gateway containers. | Their actual image references match the lock. |
| LOCK-03 | Inspect the managed and supplied Kubernetes gateway Deployments, Qwen, PostgreSQL and the three Helm releases. | Their image and chart references match the lock. |
| LOCK-04 | Ask both Keeplane installations for the running gateway version. | Both report the locked agentgateway version. |
| LOCK-05 | Inspect Django, DRF and their direct Python dependencies in the running Docker and kind apps, then compare with the local requirements file. | Exact locked versions are installed in both and their package metadata names a permitted BSD license. |
