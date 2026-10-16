# Database schema readiness

- A database with every migration known to this app is ready, using one read query.
- A missing known migration returns 503 without changing the database; process liveness stays 200.
- Extra migrations from a newer app do not remove an older worker from service.
- A database outage returns a generic 503; the next successful probe recovers without restart.
- Django's original or fully squashed migration history is accepted.

Run `python -m pytest tests/integration/test_readiness.py`. PGAPI-17 checks the
same pending-migration and recovery behavior across two actual PostgreSQL app copies.
