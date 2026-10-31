# Gateway copy readback cases

Run `.venv/bin/python -m pytest tests/unit/test_gateway_copies.py`. The fake
gateway address holds one model store; each fake copy reads it, lags a set
number of reads, stays stale or is down. No Docker or running gateway is used.
The rules are in [every gateway copy](../../docs/architecture/model-registration.md#every-gateway-copy).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GC-01 | List copy addresses, including duplicates, bad schemes, credentials, paths, control characters and more than 32. | Good lists are trimmed and deduplicated; any bad entry refuses the whole list. |
| GC-02 | Build the copies from the environment. | Each copy uses the gateway's key files; no list confirms at once; a bad list confirms nothing. |
| GC-03 | One copy lags two reads behind the store. | Keeplane waits and confirms when every copy reads the model in the same pass. |
| GC-04 | One copy stays stale, is down, raises an error or answers malformed. | The change is unconfirmed: "1 of 2 gateway copies confirmed it." |
| GC-05 | A copy holds the same definition at another revision. | Not confirmed; the fingerprint binds the revision. |
| GC-06 | Remove a model while one copy still lists it. | Unconfirmed until that copy stops listing it. |
| GC-07 | Read the copies. | Only the model resource listing is read, with no write, model call or connection retry. |
| GC-10 | Add a model; one copy lags. | Approved once every copy reads it. |
| GC-11 | Add a model; one copy stays stale. | 503, nothing approved, the new definition removed; the other model's definition and setup are unchanged. |
| GC-12 | Add a cloud model with a shared key; one copy is down. | 503, nothing approved, definition and key file removed. |
| GC-13 | Narrow a model's classes while a copy is down. | Saved; no copy is read. |
| GC-14 | Widen a model's classes while a copy is down, then again once it is back. | First 503 with nothing saved and the earlier setup kept; then saved. |
| GC-15 | Approve a changed definition that one copy hasn't read. | 503; the earlier approval is unchanged. |
| GC-16 | Replace a shared key; one copy doesn't read the new definition. | 503 "The previous key is still active."; the previous definition and key file are back. |
| GC-20 | Remove a model Keeplane added; one copy lags. | Removed and acknowledged once no copy lists it. |
| GC-21 | Remove a model with a shared key; one copy still lists it. | 503 saying developers can't use it and to check the gateway; approval and key file are gone; other models stay. |
| GC-22 | Remove setup for a model added outside Keeplane. | No copy is read; the gateway model is kept. |
| GC-23 | Add and remove with no copies listed. | Works as before, confirmed by the gateway address alone. |
