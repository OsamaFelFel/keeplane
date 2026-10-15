# Private runtime authorization

Run `python -m pytest tests/integration/test_runtime_callback.py` with isolated Django storage.

- A current developer session and private gateway credential return only canonical actor/project/model IDs.
- Missing, malformed or wrong gateway credentials deny without reflection; missing or invalid operator configuration fails closed. Atomic key replacement withdraws the old credential immediately.
- Cookies, expired/revoked sessions and disabled accounts cannot replace explicit developer authentication.
- Unknown projects and ambiguous access deny without registering anything. Admins cannot bypass class, outside-model or approval-withdrawal restrictions.
- Gateway and storage failures return 503; client actor/class claims and prompt bodies are rejected.
- Malformed, deeply nested, oversized or non-JSON metadata is rejected. Responses are not cached.
