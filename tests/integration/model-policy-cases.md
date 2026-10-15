# Current model eligibility

Run `python -m pytest tests/integration/test_model_policy.py` against the isolated Django database.

- A classed project gets only models approved for its stored class.
- Classes off, or an unclassified project, permits all currently set-up models.
- Turning classes back on restores the restriction.
- Models added outside Keeplane, removed models and changed gateway definitions are excluded.
- Reapproval restores a changed model; withdrawing class approval takes effect on the next query from either service instance.
- A rolled-back edit does not withdraw an existing approval.
- Unavailable or malformed gateway state, missing settings, malformed approvals and database failures produce no eligibility decision.

This internal service assumes that its caller has authenticated the developer and authorized the requested project. It does not establish project access, provider-key availability, gateway enforcement or request provenance. Live replica and final-destination tests belong to the runtime integration.
