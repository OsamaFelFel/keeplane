# Current model eligibility

Run `python -m pytest tests/integration/test_model_policy.py` against the isolated Django database.

- A classed project gets only models approved for its stored class.
- MP-01 Classes off, or an unclassified project, permits all currently set-up models.
  Turning classes back on restores the restriction.
- MP-02 Models added outside Keeplane, removed models and changed gateway definitions are excluded,
  even for an unclassified project.
- Reapproval restores a changed model; withdrawing class approval takes effect on the next query from either service instance.
- A rolled-back edit does not withdraw an existing approval.
- Internal personal-key setup keeps the same class and current-definition gates;
  it does not block other models. It grants no provider-key or dispatch capability.
- Public Add, editing an internal personal-key record and the preview Ask helper
  refuse personal-key work before gateway calls. The final runtime callback also
  refuses it until developer-key selection is implemented.
- MP-03 A fresh installation, before an admin first saves a data-class or model setting,
  has no settings row: the policy reads the defaults (data classes off, Spec 005 ST18)
  and, with no model approved, permits no model. It does not write the row. Once a
  setting is saved, the stored policy applies. A database failure still gives no decision.
- Unavailable or malformed gateway state, settings missing while models are approved,
  malformed approvals and database failures produce no eligibility decision.

This internal service assumes that its caller has authenticated the developer and authorized the requested project. It does not establish project access, provider-key availability, gateway enforcement or request provenance. Live replica and final-destination tests belong to the runtime integration.
