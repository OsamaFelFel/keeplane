# Internal model authorization

Run `python -m pytest tests/integration/test_model_authorization.py` in the isolated Django database.

- A current session, registered project, explicit access approval and eligible model return only canonical account, project and model IDs.
- Missing, invalid, expired, revoked, disabled, deleted and password-invalidated sessions stop before project policy or gateway reads.
- Unknown project context is refused without registering it.
- Previous project usage grants nothing; denied, unknown or ambiguous project-access answers stop the call.
- A project-access policy must be configured explicitly; there is no permissive default.
- Admin accounts receive the same model restrictions. Withdrawal is checked on the next call.
- Gateway or project-storage outages produce no authorization decision.

This service exposes no HTTP route, issues no credentials and sends no model traffic. It does not select the organization's project-access rule, attest repository/content origin, cancel already authorized calls or establish final-destination enforcement.
