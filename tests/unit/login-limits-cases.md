# Sign-in attempt limit cases

**Edition:** Open Source. Run `python3 tests/unit/test_login_limits.py`.
The SQLite preview permits five attempts per case-insensitive username within
one minute. A successful sign-in clears that account's budget. The reservation
commits before password checking, so workers sharing the store share the limit.

| Case | Action | Expected result |
| --- | --- | --- |
| LL-01 | Exhaust known and unknown account budgets. | Both return the same 429 and retry delay; no session or sign-in Audit record exists. |
| LL-02 | Restart the store and change username casing. | The existing limit still applies. |
| LL-03 | Advance to just before and then at expiry. | Retry delay reaches one second; a correct password works at expiry. |
| LL-04 | Sign in successfully after four failures. | Earlier failures are cleared. |
| LL-05 | Send eight concurrent wrong attempts with mixed username casing. | Only five reach password verification; three return 429. |
| LL-06 | Make limit storage unavailable. | Sign-in returns 503 and creates no session. |
| LL-07 | Rotate the infrastructure password after exhausting budgets. | The first admin recovers; other account budgets remain limited. |
| LL-08 | Let an unknown account bucket expire and try another account. | Expired state is pruned; only a hashed username remains. |

These cases prove the existing local store. PostgreSQL identity, distributed
rate limiting, network-source limits and the release identity choice remain
separate release work.
