# PostgreSQL chart cases

Run `python -m pytest tests/integration/test_postgres_chart.py` with Helm available.

| Case | Check |
| --- | --- |
| PGCHART-01 | Managed and supplied-gateway deployments render two PostgreSQL app copies without SQLite storage. |
| PGCHART-02 | Missing database, identity, CA or storage configuration refuses installation. |
| PGCHART-03 | Migrations use a separate credential and never expose it to serving copies. |
| PGCHART-04 | Conflicting storage modes, shared migration credentials and multiple SQLite copies refuse installation. |
| PGCHART-05 | Database TLS verification, HTTPS origin and separate readiness/liveness are configured. |
| PGCHART-06 | An externally prepared schema can disable the migration Job. |
| PGCHART-07 | PostgreSQL installs reject missing image digests, mutable tags and malformed SHA-256 digests before creating workloads. |
| PGCHART-08 | App copies, migration and supplied-gateway preflight use exactly the same pinned image. |

Local SQLite trial chart checks still accept their locally built image tags.
The Kubernetes PostgreSQL fixture aliases its already loaded image by the actual
containerd manifest digest, without a registry upload or download. Its app and
migration workloads exercise that reference during the deployment regression.
