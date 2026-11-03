# Fixture model stream cases

**Edition:** Open Source. [`test_model_fixture_stream.py`](test_model_fixture_stream.py)
runs the fixture model in [`fixtures/mock_model.py`](../fixtures/mock_model.py)
on a loopback port. The live copy-stops cases (K8S-18 and K8S-19 in the
[local Kubernetes cases](../e2e/kubernetes-cases.md)) stop a gateway copy while
this paced reply streams through it.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| MFS-01 | Ask the fixture for a streamed reply with the prompt "keeplane slow stream". | The reply is chunked with no length, and arrives as 40 word chunks spaced by the fixture's pause, then a chunk with finish reason "stop", then `[DONE]`. |
| MFS-02 | Close the connection after the first chunk, then ask for an ordinary streamed and unstreamed reply. | The fixture keeps serving: the ordinary stream sends its usual chunks and `[DONE]`, and the unstreamed reply is "mock answer". |
