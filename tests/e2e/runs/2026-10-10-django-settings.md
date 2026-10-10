# Django Data Classes and Audit cutover: local evidence

Data Classes and Audit now enter Django and DRF through the Keeplane front
server. The established stores retain the same settings, approval, and audit
records. The older front-server handlers for these routes were removed.

The documented [Data Classes cases](../data-classes-cases.md) check the off
state, starter classes, model approval, edits, rejection, persistence, and
cleanup. The [Audit cases](../audit-cases.md) check independent options,
records, filters, authorization, and mandatory break-glass sign-ins. Both case
documents describe the expected behavior in plain English.

| Preview | Focused result | Evidence |
| --- | --- | --- |
| Docker | 3 of 3 suites; 23 cases passed | [Docker JSON](2026-10-10-django-settings-docker-focused.json) |
| Managed kind | 2 of 2 suites; 20 cases passed | [kind JSON](2026-10-10-django-settings-kind-focused.json) |

The [full regression](2026-10-10-django-settings-full-regression.json) passed
all 48 suites and all 290 case records on the final Docker and kind preview
images. It included account sign-in, model management, gateway outage and
failover, the customer-run gateway, key rotation, and both integrated journeys.
The runner restored the initial Data Classes mode. Docker remains available at
port 3000 and managed kind at port 13000.

This is an HTTP cutover for the local trial. Release PostgreSQL persistence,
project-class enforcement, held-request records, and model-answer records
remain separate product work.
