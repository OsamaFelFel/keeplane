# S8 local runner flow in the live previews

**Date:** 8 October 2026  
**Product source:** Spec 004, D114–D116 and D123
**Targets:** Docker preview (`127.0.0.1:3000`), managed kind preview
(`127.0.0.1:13000`), app-only kind preview (`127.0.0.1:13001` through a
loopback port forward)

| Case | Result | Evidence |
| --- | --- | --- |
| LOCAL-21 | Pass in Docker and both kind modes | Find models listed Qwen's `qwen2.5-coder:0.5b` in Docker and managed kind, and the fixture's `mock-local` in app-only kind. The selected model answered the pre-save probe and a later request through its configured gateway. |
| LOCAL-22 | Pass in Docker and both kind modes | An unserved model and a runner address outside the preview allowlist returned HTTP 400; neither model appeared in the catalog. |
| LOCAL-23 | Pass by browser inspection | The page contained no gateway product name or version and no Try panel. With the Docker gateway stopped, the exact unavailable notice appeared, Add model was disabled and the table said `Models unavailable`. After the gateway restarted, Try again restored the list and Add model. |
| LOCAL-10 | Pass by browser measurement | Add model dialog width was 560px; Provider, Runner address and Model controls were each 44px high. |
| Duplicate add | Pass by browser inspection | Adding the already registered Qwen model kept the dialog open and showed `qwen2.5-coder:0.5b from Local runner is already added.` directly below Model. |

Commands used for the API regression:

```sh
KEEPLANE_BASE_URL=http://127.0.0.1:3000 python3 tests/e2e/test_runner_flow.py
KEEPLANE_BASE_URL=http://127.0.0.1:13000 python3 tests/e2e/test_runner_flow.py
KEEPLANE_BASE_URL=http://127.0.0.1:13001 \
  KEEPLANE_RUNNER_URL=http://model.supplied-gateway.svc.cluster.local:18080 \
  KEEPLANE_EXPECTED_MODEL=mock-local KEEPLANE_EXPECTED_ANSWER='mock answer' \
  python3 tests/e2e/test_runner_flow.py
```

The first Docker registration returned HTTP 200 and a real Qwen answer, while
the immediate model-list request had not caught up. A bounded catalog retry
observed it; a repeat run passed all checks. `test_local.py` also passed all
seven cases against Docker after this change. The UI waits for catalog
propagation after registration.

After the final kind rebuild, 52 executable checks passed across the versioned
`2026-10-08-s8-*.json` files in this directory: Docker local, Qwen, guarded
endpoint, runner and runtime cases; managed kind local, Qwen, runner, runtime
and gateway failover cases; app-only runner cases; management-read failure
injection; and the stack lock. The
browser-only unavailable and duplicate states were inspected separately as
described above. Both local previews were restored to a working state after
the temporary Docker gateway outage test.

The preview still lacks data-class approvals, key management, edit/remove,
routing policy and admin sign-in. The runner address allowlist is a temporary
preview safeguard, and this run does not close Spec 004.
The supplied gateway still showed a ten-second model-configuration read in its
log during the final app-only pass; Keeplane's bounded retry let that run
complete. The gateway stall remains a release-selection issue.
