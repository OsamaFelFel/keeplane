# Django model removal cutover, 10 October 2026

Protected `DELETE /api/models/{id}/setup` now reaches Django in the Docker,
managed kind, and customer-run gateway previews. Its use case leaves a
customer-added gateway model in place when removing Keeplane setup. For a
Keeplane-owned model, it checks the gateway revision before deletion and uses
the gateway's management credential. The real local catalog writes a settings
Audit record in the removal transaction when that Audit option is enabled.

| Check | Result | Evidence |
| --- | --- | --- |
| [Removal backend cases](../../unit/model-removal-cases.md) | 7/7 pass | [Unit run](../../unit/runs/2026-10-10-django-model-removal.txt) |
| Existing listing and adapter cases after the rename | 5/5 pass | [Unit run](../../unit/runs/2026-10-10-django-model-listing-after-removal.txt) |
| [Live removal and Audit cases](../model-removal-cases.md), Docker | 8/8 pass | [Docker run](2026-10-10-django-model-removal-audit-docker.json) |
| Live removal and Audit cases, managed kind | 8/8 pass | [Kind run](2026-10-10-django-model-removal-kind.json) |
| Protected customer-run gateway flow | 4/4 pass | [Existing-gateway run](2026-10-10-django-model-removal-existing.json) |
| Complete current-feature regression | 48/48 suites, 290 case records pass; original Data Classes mode restored | [Full run](2026-10-10-django-model-removal-regression.json) |

The live Audit case switches settings Audit on only for its test and restores
the previous setting. The live cases cover no-key local models; shared-key file
cleanup is covered by the backend case and remains to be exercised through a
customer-installed gateway before release. Model Add and Set up writes, local
SQLite trial persistence, and partial-failure reconciliation remain outside
this cutover. The gateway is still an integration trial, not a release
selection; this result makes no project-class bypass claim.
