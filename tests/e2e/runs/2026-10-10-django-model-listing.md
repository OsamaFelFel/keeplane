# Django Models listing cutover, 10 October 2026

The protected `GET /api/models` request now reaches Django on the internal
loopback listener in the Docker, managed kind, and customer-run gateway
previews. A small model-listing use case joins the live gateway registry with
Keeplane's approval records. The agentgateway read adapter uses separate
runtime and management credentials. Model registration, setup, removal, Data
Classes, Audit, and the local SQLite stores still use the trial server; the
PostgreSQL release cutover is not complete.

## Executed cases

| Check | Result | Evidence |
| --- | --- | --- |
| [Model-listing backend cases](../../unit/model-listing-cases.md) | 5/5 pass | [Unit run](../../unit/runs/2026-10-10-django-model-listing.txt) |
| Protected preview parity, accounts, approval, and customer-run gateway | 6/6 suites, 68 cases pass | [Focused run](2026-10-10-django-model-listing-focused.json) |
| Complete current-feature Docker and kind regression | 48/48 suites, 288 case records pass; original Data Classes mode restored | [Full run](2026-10-10-django-model-listing-regression.json) |

An unsigned Docker or managed kind Models request returned 401; a signed-in
first admin received the live model list on each. Both UI addresses remained
available after the rollouts. The full regression includes model approval,
add, edit, replacement, removal, cloud keys, Audit, gateway failure, replica
failover, and generated Qwen answers.

The earlier [Docker Qwen timeout](2026-10-10-react-models-stage.md) was a
direct 256-token CPU generation probe. Its 120-second window was increased to
300 seconds per model request because LOCAL-20 checks the token limit, not
latency. The expected 256 tokens and length finish reason did not change. This
full run passed that case in 45.5 seconds and kind's case in 44.6 seconds; the
local runtime's latency remains variable.
