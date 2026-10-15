# CLI project registration

- **CLI-PROJ-01:** Send only the explicit canonical UUID/name and Bearer session;
  show the server-preserved name rather than claiming a rename.
- **CLI-PROJ-02:** Refuse malformed context and unexpected response fields;
  session, validation and storage failures expose no server body or credential.
- **CLI-PROJ-03:** Real Django contract checks record the authenticated account,
  preserve first use/name/class on repeat, and create nothing after revocation.

Run `python -m pytest tests/unit/test_cli_project_registration.py`.
