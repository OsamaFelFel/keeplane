# PostgreSQL deployment cases

**Edition:** Open Source; Enterprise extends the same account/storage contract.

Run `.venv/bin/python -m pytest tests/integration/test_postgres_chart.py -m live` to inspect the chart contract:

| Case | Expected behavior |
| --- | --- |
| PGCHART-01 | Both gateway modes render two PostgreSQL app copies without SQLite volumes. Existing mode installs no gateway. |
| PGCHART-02 | Missing database, Secret, CA or provider volume configuration refuses rendering. |
| PGCHART-03 | Only the separate migration Job receives migration credentials. It does not receive the first-admin password. |
| PGCHART-04 | Mixed SQLite/PostgreSQL mode, shared migration credentials and multi-copy SQLite are refused. |
| PGCHART-05 | Database connections require hostname-verified TLS. Browser origin requires HTTPS. Readiness and liveness use separate endpoints. |
| PGCHART-06 | An operator may disable the Job after arranging schema migrations separately. |

Build with `docker build --target postgres -t keeplane-preview:postgres-local -f components/control-plane/Dockerfile .`, then run
`.venv/bin/python -m pytest tests/e2e/test_postgres_deployment.py -m live --output NEW.json` against the
isolated `kind-keeplane-netpol` cluster with its existing ingress controller:

| Case | Expected behavior |
| --- | --- |
| PGDEPLOY-01 | Helm migrates a clean database with its separate role. Two app copies serve HTTPS sign-in and a UUID identity. |
| PGDEPLOY-02 | The real app connection uses TLS. Its role cannot create tables, change the user schema or create roles. Wrong database hostname, wrong CA and plaintext connections are refused for the expected reason. |
| PGDEPLOY-03 | The signed-in admin sets up the baseline model, registers a database-owned model and receives an answer through the actual gateway. |
| PGDEPLOY-04 | The same browser session works on each app copy. Neither pod receives the migration Secret. |
| PGDEPLOY-05 | A second Keeplane release uses that separately installed gateway, the shared account database and model approval. It receives an answer and creates no gateway. |
| PGDEPLOY-06 | Replacing database and app pods preserves identity, session and approval on the database PVC. |
| PGDEPLOY-07 | A dump restored into a fresh database preserves sessions, Audit and approvals after both installations are reconfigured. |

The fixture generates its own credentials and CA, creates one unique namespace,
and removes it plus its port-forwards. It does not modify either review preview.
Single-node PVCs, a disposable gateway database and fixed model answers do not
prove production database availability, production volume semantics, real
provider Secret delivery or runtime project/class enforcement.
