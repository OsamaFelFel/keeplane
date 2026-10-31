# Gateway copy readback cases

Run `.venv/bin/python -m pytest tests/unit/test_gateway_copies.py`. The fake
gateway address holds one model store; each fake copy reads it, lags a set
number of reads, stays stale, hangs or is down. A fake clock counts passes
except in GC-08, which uses real time. No Docker or running gateway is used.
The rules are in [every gateway copy](../../docs/architecture/model-registration.md#every-gateway-copy).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GC-01 | List copy addresses, including duplicates, bad schemes, credentials, paths, control characters and more than 32. | Good lists are trimmed and deduplicated; any bad entry refuses the whole list. |
| GC-02 | Build the copies from the environment. | Each copy uses the gateway's key files; no list confirms at once; a bad list confirms nothing. |
| GC-03 | One copy lags two reads behind the store. | Keeplane waits and confirms when every copy reads the model in the same pass. |
| GC-04 | One copy stays stale, is down, raises an error or answers malformed. | The change is unconfirmed: 1 of 2 copies. |
| GC-05 | A copy holds the same definition at another revision. | Not confirmed; the fingerprint binds the revision. |
| GC-06 | Remove a model while one copy still lists it. | Unconfirmed until that copy stops listing it. |
| GC-07 | Read the copies. | Only the model resource listing is read, with no write, model call or connection retry, and no read timeout beyond the deadline. |
| GC-08 | Four of five copies hang and ignore their timeout. | The check ends within its deadline (5 seconds by default) with 1 of 5 confirmed. |
| GC-09 | Set up the file-owned preview model with two copies listed; one copy holds a store entry for it, or is down. | Confirmed when copies answer with no overriding entry, and the setup is saved; an overriding entry or a down copy is unconfirmed. |
| GC-10 | Add a model; one copy lags. | Approved once every copy reads it. |
| GC-11 | Add a model; one copy stays stale. | 503 "new-model wasn't added", "Not every gateway copy confirmed it: 1 of 2 did. Nothing was saved. Check the gateway and try again."; nothing approved, the definition removed; the other model is unchanged. |
| GC-12 | Add a cloud model with a shared key; one copy is down. | 503 "wasn't added"; nothing approved, definition and key file removed. |
| GC-13 | Narrow a model's classes while a copy is down. | Saved; no copy is read. |
| GC-14 | Widen a model's classes while a copy is down, then again once it is back. | First 503 "edited wasn't changed", "Not every gateway copy confirmed the change: 1 of 2 did. Nothing was saved, and its earlier setup stays. Check the gateway and try again."; then saved. |
| GC-15 | Approve a changed definition that one copy hasn't read. | 503 "wasn't changed"; the earlier approval is unchanged. |
| GC-16 | Replace a shared key; one copy doesn't read the new definition. | 503 "keyed wasn't changed", "Not every gateway copy confirmed the new key: 1 of 2 did. Nothing was saved, and the earlier key stays. Check the gateway and try again."; the previous definition and key file are back. |
| GC-17 | Move an unchanged model from no key to each developer's own key while a copy is down. | Saved; no copy is read. |
| GC-18 | Use an invalid copy list: add a model, narrow classes, widen classes, remove a model. | A warning is logged; the add and the widening are refused with the copy-list message and nothing saved; narrowing is saved; the removal stands with "Developers can't use it, but Keeplane can't check every gateway copy …". |
| GC-20 | Remove a model Keeplane added; one copy lags. | Removed and acknowledged once no copy lists it. |
| GC-21 | Remove a model with a shared key; one copy still lists it. | 503 "gone was removed", "Developers can't use it, but 1 of 2 gateway copies still list it. Check the gateway."; approval and key file are gone; other models stay. |
| GC-22 | Remove setup for a model added outside Keeplane. | No copy is read; the gateway model is kept. |
| GC-23 | Add and remove with no copies listed. | Works as before, confirmed by the gateway address alone. |
| GC-24 | The database reports a failed commit that was kept, while one copy still lists the model; then again with every copy caught up. | First 503 "was removed" with the approval gone; then 200. |
| GC-25 | Build model management and remove a model through the app. | The app's copy list reaches both the add/edit use case and the removal view. |
