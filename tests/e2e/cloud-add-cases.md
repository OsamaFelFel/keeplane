# Cloud model registration: protected Docker preview

These cases use agentgateway and a local authenticated endpoint that speaks the
OpenAI and Anthropic request formats. The fixture is a stand-in for a paid
provider; it proves our registration, key handling, gateway transport, and
rollback paths. It does not prove connectivity or compatibility with either
provider's live service.

The fixture key is created under `/private/tmp/keeplane-accounts-trial` and is
never committed or printed by the verifier. Run `python3 deploy/local/up.py`
before `python3 tests/e2e/test_cloud_add.py`. The suite writes its JSON result
to `tests/e2e/runs/2026-10-09-cloud-add.json`.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| CADD-01 | Without signing in, try to register a cloud model. | The request is rejected; no gateway model is created. |
| CADD-02 | As admin, add an OpenAI-format model with a shared key and Public approval. Ask it a question. | It answers through agentgateway and appears as an approved cloud model with a shared key. |
| CADD-03 | Inspect the model list, API response, gateway resource, and key file. | No API returns the key; gateway stores only a file reference; the file is restricted to the gateway user. |
| CADD-04 | Try to add the same provider and upstream model again. | The duplicate is rejected and no additional key file is written. |
| CADD-05 | Add a model with a wrong provider key. | The model does not get approval, the gateway entry is removed, and the temporary key file is removed. |
| CADD-06 | Add an Anthropic-format model with a shared key. Ask it a question. | It answers through agentgateway and appears with the right provider and approvals. |
| CADD-07 | Change the OpenAI model's approved classes from Public to Internal. | The shared-key setting remains and the model still answers. |
| CADD-08 | Request approval for an unknown data class. | The request fails before any model or key is saved. |
| CADD-09 | Remove both models added by Keeplane. | Gateway entries, approvals, and their key files are removed. |

The suite compares its key-file listing before and after the cases and cleans
up trial models even if an assertion fails. A separate browser review is still
needed for visual alignment with the product canvas.
