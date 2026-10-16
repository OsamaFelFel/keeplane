# CLI issuance with PostgreSQL

Run `test_cli_oauth_postgres_concurrency.py` with `-m optional`, the pinned OAuth
trial dependencies and Django settings pointing at a disposable PostgreSQL
database. The database role must be able to create pytest's test database. These
cases skip SQLite and use only synthetic accounts and credentials.

For both browser and approved device grants:

- Two requests try to consume the same grant. The first holds the actual owner
  row lock; PostgreSQL must report the second request waiting on a lock. Releasing
  the first permits exactly one credential pair, and consumes the grant once.
- Two requests try to rotate the same refresh token. One rotates it; the second
  detects replay and withdraws that family, including the newly issued pair.
- Global account withdrawal occurs while issuance is waiting on the owner lock.
  Issuance must recheck the live grant and return no new credential.

Each worker uses its own database connection. Fixture gates only control timing;
the authorization, grant processing and revocation use the real Django/Toolkit
views. These checks do not prove a browser, installed gateway or model dispatch.

The lock observer refreshes its transaction's activity snapshot before each read,
as [PostgreSQL documents](https://www.postgresql.org/docs/16/monitoring-stats.html).
The withdrawal case also checks that the blocked request is waiting on the exact
database process holding its owner lock.
