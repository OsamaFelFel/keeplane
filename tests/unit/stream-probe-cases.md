# Stream probe cases

**Edition:** Open Source. [`test_stream_probe.py`](test_stream_probe.py) checks
the slow-stream fixture (`tests/fixtures/mock_model.py`) and the stream probe
(`tests/support/stream_probe.py`) that the live case K8S-18 runs in the app pod.
Every server is a loopback HTTP server in the test process.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| SPROBE-01 | Ask the fixture model for a streamed answer with the slow-stream marker in the prompt. | The probe receives each piece separately, in order, then reports the whole answer, `finish_reason` `stop` and `[DONE]`, with no error. |
| SPROBE-02 | Ask the fixture model for a streamed answer without the marker. | The quick fixture answer ("mock answer") is unchanged. |
| SPROBE-03 | Stream from a server that sends two pieces and then closes the connection mid-body, and from one that ends the body properly but sends no finish or `[DONE]`. | Both report only the two pieces, no finish and no `[DONE]`, so neither looks complete. The cut connection is also reported as an error (`IncompleteRead`). |
| SPROBE-04 | Stream from an address where nothing listens. | The probe reports an error, no status and no `[DONE]`. |
