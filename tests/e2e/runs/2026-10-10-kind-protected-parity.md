# Protected kind preview: Docker account-flow parity

Run on 10 October 2026 against the isolated `kind-keeplane` cluster and
`http://127.0.0.1:13000`. Docker remained available on port 3000. The managed
kind app used the same first-admin password file, with a separate persistent
account and approval store. The separately installed existing-gateway test app
remained internal and unprotected.

| Plain-English cases | Result | Evidence |
| --- | --- | --- |
| Sign in, list and manage accounts, reject spoofed identity and foreign sign-in origin, and open React pages | 21/21 | [kind users](2026-10-10-kind-users-react.json), [Docker users](2026-10-10-docker-users-origin.json) (21/21) |
| Turn Data Classes on and off, manage approvals, and retain changes across a kind app restart | 11/11 | [Data Classes](2026-10-10-kind-data-classes.json) |
| Record and filter Audit events, enforce roles, and retain records across a kind app restart | 9/9 | [Audit](2026-10-10-kind-audit-developer.json) |
| Register and call fixture models; refuse an unknown model | 7/7 | [local gateway](2026-10-10-kind-local.json) |
| Register and call real local Qwen | 2/2 | [Qwen](2026-10-10-kind-qwen.json) |
| Discover runner model and context, add it, and refuse invalid choices | 5/5 | [runner](2026-10-10-kind-runner.json) |
| Read both gateway replicas, replace one pod, and verify existing-gateway isolation | 7/7 | [replica and existing gateway](2026-10-10-kind-replica.json) |

The first protected fixture call failed because the app could not verify the
gateway's file-owned `local-fixture` definition. The chart now mounts the
gateway ConfigMap into the app, and the rerun passed. The first standalone
Audit run failed because a fresh kind store had Data Classes off; the test now
enables the required mode and restores it. A direct sign-in origin probe found
that the legacy endpoint accepted a foreign Origin; both Docker and kind now
reject it, as the 21-case account reports show.

This is local functional parity for the listed flows. It does not prove that
the trial chart is a production release, that Docker and kind share records,
or that the gateway enforces project-class policy against bypass.

The complete documented regression then passed **33/33 suites and 173/173
case records** across Docker, kind and isolated component checks. The
[full run](2026-10-10-kind-parity-regression.json) includes commands, case IDs,
durations and the tested Git state.
