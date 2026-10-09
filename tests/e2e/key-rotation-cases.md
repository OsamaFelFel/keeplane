# Replace a shared cloud model key in the protected Docker preview

These cases use the real local agentgateway and the disposable authenticated
OpenAI-format mock. They do not use a paid provider account. The verifier
temporarily changes the mock's expected key and restores it before exiting;
neither key value is printed or committed.

Run `python3 deploy/local/up.py` and then
`python3 tests/e2e/test_key_rotation.py`. Its JSON result is saved in `runs/`.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| ROT-01 | Add a model with a shared key, then enter a replacement key that is too short. | Keeplane rejects the edit before changing the model or writing another key file. |
| ROT-02 | Try a well-formed but wrong replacement key. | Keeplane rejects it. The old model still answers, its approved class stays the same, and no extra key file remains. |
| ROT-03 | Leave Replace shared key empty and change the approved class. | The current key remains in use, and the model still answers. |
| ROT-04 | Change the mock to accept a new key and replace the model's key with it. | Keeplane validates the new key through a temporary gateway model, updates the original gateway model and approval, and removes the old key file. The model answers with the new key. |
| ROT-05 | Remove the model Keeplane added. | Its gateway resource, approval, and remaining key file disappear; the mock's original expected key is restored. |

The temporary verification model never receives Keeplane approval. If a
gateway failure prevents its safe removal, Keeplane reports that it needs
attention and keeps the corresponding key file so the gateway reference does
not break. A failed replacement leaves the approved model's existing route
alone whenever its definition can be verified.
