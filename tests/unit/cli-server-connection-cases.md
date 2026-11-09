# CLI server connection

- **CLI-CON-01:** Canonicalize the requested project UUID, send only the explicit
  Bearer session and print the server's eligible model IDs in stable order.
- **CLI-CON-02:** Refuse insecure origins, credential-bearing URLs, redirects,
  malformed/duplicate/wrong-project catalogs and oversized responses.
- **CLI-CON-03:** Session, access and policy failures reveal no server body or
  credential. The command saves no credentials and ignores ambient proxy settings.
- **CLI-CON-04:** A server that also gives its gateway address (`gateway_url`, an
  address or null; task 009-02) is accepted, and the account the CLI uses is
  still only the ID, user name and role. Saving the address is task 009-02b.

Run `python -m pytest tests/unit/test_cli_server_connection.py`.
