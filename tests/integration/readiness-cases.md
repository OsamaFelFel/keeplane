# Database schema readiness

- With CLI sign-in off, a database with every known migration is ready using one
  read query; optional sign-in models are not imported.
- Enabled CLI sign-in also requires both fixed clients to match. Missing,
  changed or unavailable clients return a generic 503 without writes or row locks.
- A missing known migration returns 503 without changing the database; process liveness stays 200.
- Extra migrations from a newer app do not remove an older worker from service.
- A database outage returns a generic 503; the next successful probe recovers without restart.
- Django's original or fully squashed migration history is accepted.

Run `python -m pytest tests/integration/test_readiness.py`. PGAPI-17 checks the
same pending-migration and recovery behavior across two actual PostgreSQL app copies.
