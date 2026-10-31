# List the models I can switch to when mine is down

Spec 004 ST16, owner decision of 31 October 2026: Keeplane never switches the
model for an outage or a task that is too big; it lists the allowed
alternatives. Run `python -m pytest tests/integration/test_model_alternatives.py`.

| Case | Situation | Expected result |
| --- | --- | --- |
| ALT-01 | Two other models are allowed | Both are listed by model ID; the response is not cached. |
| ALT-02 | Alternatives are listed | Nothing moves: the requested model still answers at the gateway and the next model choice keeps it. |
| ALT-03 | No other model is allowed | The list is empty; the CLI shows the no-models message. |
| ALT-04 | The only other model is for another class, set up but not installed, gateway-only, needs a missing own key, or lost its shared key file | It is not listed; the shared fallback filter (`next_allowed`) decides. |
| ALT-05 | Asking about another model | The requested model is never listed. A Personal model is listed only while the developer's own key is usable. |
| ALT-06 | A model's class approval is withdrawn | It drops from the list. |
| ALT-07 | Responses | No key, fingerprint, session or directory appears. |
| ALT-08 | Missing or extra query fields, an empty or unallowed model | 400, 400, 400 and 403. |
| ALT-09 | Invalid session, policy outage, unknown project | 401, 503 “Model alternatives are unavailable”, 403. |
| ALT-10 | A well-formed ID of a project not registered here, or a registered project the access policy refuses for this developer | 403 with no list. Open Source has one organization; the refused case stands in for a stricter organization rule. |

The cases reuse the real Django accounts, policy, enrollment files and owner-key
registrations of the [model choice cases](model-choice-cases.md).
