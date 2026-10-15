# Control plane

Gunicorn serves the Django/DRF application through `config.wsgi`. The application
uses Django accounts, password hashing, database sessions and ORM storage.

| Directory | Responsibility |
| --- | --- |
| `config/` | Settings, root URLs and serving configuration |
| `accounts/` | Accounts, roles, sign-in budgets and Editions preferences |
| `model_registry/` | Model setup, approvals and registration use cases |
| `data_classes/` | Class settings and approved-model associations |
| `audit/` | Mandatory sign-in and optional event records |
| `integrations/` | Gateway and runner API adapters |
| `common/` | Shared request protection, storage boundaries and service assembly |

Each domain owns its models, migrations, services, views and URLs. Keep business
rules in services and external component requests in adapters.

The local launcher prepares credentials and runs migrations before starting the
server. SQLite is for the single-process local installation; shared deployments
use PostgreSQL. See [local setup](../../docs/guide/local-preview.md) and
[PostgreSQL operations](../../docs/guide/postgres-accounts.md).

Python tests live in the repository's `tests/` tree and run through pytest.
The one-time `import_preview` command preserves earlier local records without
changing their original files. Serving workers never run schema migrations.
The original Django migration is retained. Moving models between apps changes
their migration state only, preserving existing PostgreSQL tables and records.
