# Deliver each actor's provider key

This disposable trial asks whether the pinned native gateway can use a different
server-held provider key on each request. Two real Django sessions use the same
registered project and approved model. The trusted final-model authorizer returns
an `Authorization` header chosen from its authenticated `actor_id`; native HTTP
`includeResponseHeaders` replaces the request header before provider dispatch.
No authorization results are cached.

| Request | Expected result |
| --- | --- |
| A has a key; B has never added one | A answers; B is denied without provider contact. |
| B adds a key, then requests alternate between A and B | Each request uses its actor's key. |
| A's key is withdrawn | A is denied before provider contact; B can still answer. |
| A's key is restored or replaced | The next request uses the current key. |
| Client forges provider or actor headers | They cannot choose the server key and do not reach the provider. |
| Client replaces its Keeplane session with a forged provider credential | Authentication fails without provider contact. |

The selected-model callback runs before key injection. Static backend credentials
would overwrite that injected header, and removing `Authorization` afterward
would erase it, so neither is configured on this test model. Context and forged
provider headers are removed. Keys are never returned to the client or written
to evidence; reports contain actor labels, contact names and booleans only.

Run with the [native fixture prerequisites](native-runtime-authorization-cases.md):

```sh
python -m pytest tests/integration/test_native_actor_provider_keys.py -m live -q
```

The key map and response-header wrapper exist only in the disposable fixture.
Its native model has no static key and uses the existing keyless setup approval
so the current shared-key-only production guard remains unchanged. This proves
native transport capability, not production personal-key storage, validation,
selection, precedence, encryption, customer delivery, fallback, replica handling,
TLS or release readiness. The release gateway remains unselected.
