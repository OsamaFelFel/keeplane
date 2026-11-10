# Runtime gateway address

**Edition:** Open Source and Enterprise. Spec 009 ST30, task 009-02,
[ADR 030](https://github.com/OsamaFelFel/keeplane-governance/blob/main/adrs/0030-cli-coding-runtime-and-repos.md),
journey DEV-03 (RGA-05: task 009-02b). Run `python -m pytest tests/integration/test_runtime_gateway_address.py`
with isolated Django storage.

`GET /api/runtime/session` gives a signed-in CLI the gateway address the installer
set in `KEEPLANE_GATEWAY_PUBLIC_URL`, as `gateway_url`. The CLI saves it at sign-in
(task 009-02b).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| RGA-01 | With the address set, a CLI signed in with a bearer credential reads its account, sending a different forwarded host. | 200, not cached: the account's ID, user name and role, and `gateway_url` exactly as set. The request's headers change nothing. |
| RGA-02 | With no address set, the same request, with forwarded host and HTTPS headers. | 200 with `gateway_url: null`, so the CLI can say Keeplane doesn't know the gateway address yet. Nothing is worked out from the request. |
| RGA-03 | Ask with a browser cookie only, an invalid bearer, a Basic header, or a signed-out credential. | 401, and the address is not in the response. |
| RGA-04 | Start Django with `http://127.0.0.1:5000/v1/`, empty, `http://` to another computer, and `/v1/chat/completions`. | The first starts with `http://127.0.0.1:5000/v1`, the empty one with no address. The other two stop start-up with a message naming `KEEPLANE_GATEWAY_PUBLIC_URL`: HTTPS unless the gateway is on this machine, or an address ending in `/v1`. |
| RGA-05 | Over real HTTP, the CLI reads the signed-in account with the address set to `https://keeplane.example/v1` or `http://127.0.0.1:5000/v1`, or not set. | The CLI gets the account and that address, which passes its own gateway check, or no address. Reading only the account gives the same ID, user name and role. |
