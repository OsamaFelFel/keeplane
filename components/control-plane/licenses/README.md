# Optional PostgreSQL driver

Psycopg 3.3.6 is an optional, separately replaceable dependency. The default
preview image does not install it. Its unchanged LGPL-3.0-only license text is
retained in `psycopg-3.3.6.txt`; `psycopg-3.3.6.json` records the verified wheel,
corresponding source archive, hashes and official metadata location.

The pure-Python requirement uses an independently installed `libpq`. This record
does not inventory that library, its transitive dependencies or the binary
wheels used by disposable integration tests. A release package must include
their exact source/license/notice records and satisfy the applicable replacement
and corresponding-source obligations. Keep those files when distributing the
optional driver; the Community and Enterprise application licenses are unchanged.
