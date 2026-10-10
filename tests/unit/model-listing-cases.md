# Model listing backend cases

Run `python3 tests/unit/test_model_listing.py`. These cases check the new
Django Models listing use case without a running stack; the existing E2E cases
check the protected API against the live gateway.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ML-01 | List a Keeplane-approved cloud model and an outside gateway model. | The approved model shows its key choice and classes; the outside model is not approved, and no provider secret appears in either result. |
| ML-02 | Change an approved model's gateway revision before listing it. | The old approval no longer applies. |
| ML-03 | Make either gateway registry read fail. | The API returns that failure without showing a partial model list. |
| ML-04 | Ask the adapter to read runtime and management endpoints. | It sends the corresponding separate credentials, and retries a temporary management read failure. |
| ML-05 | List a model on an allowed local runner. | It is identified as Local runner without copying the gateway's internal definition into Keeplane records. |
