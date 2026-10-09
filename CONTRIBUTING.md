# Contributing

Keeplane is at the first local integration slice. Please describe the user-visible
change and include a plain English case in `tests/e2e/cases.md` when changing a
workflow. Run `python3 tests/e2e/test_local.py` against the local Docker stack
and report the observed result. Keep credentials and real customer prompts out
of commits. Code is licensed under Apache 2.0; check the license of every
customer-installed component before proposing it for release.
