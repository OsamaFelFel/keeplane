# Protected Docker cloud registration trial — 2026-10-09

The real agentgateway 1.6.0 handled OpenAI and Anthropic format requests to a
local authenticated mock. The protected Keeplane UI and control plane registered
models with shared keys stored in a Docker volume as owner-only files. No live
OpenAI or Anthropic subscription was used, and this trial does not choose the
release gateway.

- [Cloud registration cases](../cloud-add-cases.md): 9/9 passed in the
  [JSON result](2026-10-09-cloud-add.json). An admin could add, use, edit class
  approval, and remove both native provider formats. Duplicate and wrong-key
  requests left no model approval, gateway resource, or extra key file. The
  key value was absent from the API response, model list, and gateway resource;
  the reference pointed to a file owned by gateway UID 65532 with mode 0600.
- UI fixture review at 1280px: OpenAI selection showed the model, provider-key,
  and data-class controls; the password field was masked; Save enabled only
  after a valid model ID, key, and class. Inputs and select matched the design
  system's 44px control height and dialog width. This was an interaction and
  layout check, not a live-provider test.
- The first [full sweep](2026-10-09-full-regression-cloud-add.json) passed
  26/27 suites. The gateway-down Service probe saw `/health` return 200 while
  `/api/models` returned 503 during rollout. Its [isolated recheck](2026-10-09-gateway-down-cloud-add-recheck.json)
  passed 2/2 cases.
- While adding a bounded retry to that probe, an accidental indentation inside
  its embedded Python caused a second [full sweep](2026-10-09-full-regression-cloud-add-recheck.json)
  and two [diagnostic](2026-10-09-gateway-down-convergence.json)
  [rechecks](2026-10-09-gateway-down-diagnostic.json) to fail at probe execution.
  The diagnostic report captured `IndentationError`; the product endpoints were
  not the cause. The syntax was fixed and separately parsed before the
  [corrected isolated run](2026-10-09-gateway-down-corrected.json) passed.
- The [final full regression](2026-10-09-full-regression-cloud-add-final.json)
  passed 27/27 suites and 135/135 case records. Both Docker and kind model
  runtime suites passed, and all three previews remained reachable.

Later on 9 October, the [shared-key replacement cases](../key-rotation-cases.md)
passed 5/5 and the [full regression](2026-10-09-full-regression-key-rotation.json)
passed 28/28 suites with 140/140 case records. Edit model can now keep or
replace an existing shared key. A unique temporary gateway model validates a
replacement before the approved model changes. Its
[JSON result](2026-10-09-key-rotation.json) records failed and successful
replacement, preserved approval, and key-file cleanup. The local mock's
expected key was restored after the run.

Remaining work: support real external provider endpoints in the protected
preview, developer-owned keys and key-choice changes, release-grade
secret storage across gateway replicas, and the gateway release decision. The
current local UI explicitly labels the authenticated mock so an admin will
not mistake it for a paid provider connection.
