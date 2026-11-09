# Model policy before any setting is saved

Run `python -m pytest tests/unit/test_model_policy_defaults.py`. The stored rows
are stand-ins; `tests/integration/test_model_policy.py` (MP-03) and
`tests/integration/test_runtime_catalog.py` (CAT-02) check the same rule against
a real database.

- MPD-01 No data-class settings row and no approved model: a fresh installation.
  The policy reads the defaults (data classes off, Spec 005 ST18) and permits no
  model, also for a request held by personal-data detection. It reads the row
  once and writes nothing.
- MPD-02 No settings row while a model is approved: the row was saved once and
  is lost, so the policy reads it again and, still missing, makes no decision.
- MPD-03 A first policy write that commits between the two reads: the second
  read finds the row and its stored policy applies.
- MPD-04 A stored row is read once and used as before.
