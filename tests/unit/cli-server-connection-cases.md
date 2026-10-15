# CLI server connection

- **CLI-CON-01:** Canonicalize the requested project UUID, send only the explicit
  Bearer session and print the server's eligible model IDs in stable order.
- **CLI-CON-02:** Refuse insecure origins, credential-bearing URLs, redirects,
  malformed/duplicate/wrong-project catalogs and oversized responses.
- **CLI-CON-03:** Session, access and policy failures reveal no server body or
  credential. The command saves no credentials and ignores ambient proxy settings.

Run `python -m pytest tests/unit/test_cli_server_connection.py`.
