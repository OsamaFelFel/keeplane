# Task routing cases

Spec 004 ST15 (“The rule applies”) and ST17 (“My switch beats Keeplane's
picks”), D150. Run `.venv/bin/python -m pytest tests/integration/test_task_routing.py`.
The cases reuse the real Django accounts, policy, enrollment files and
owner-key registrations of the [model choice cases](model-choice-cases.md):
a Confidential project and three allowed models, `private` (the developer's
own key), `public` and `outside`, with no known context windows.

| Case | Situation | Expected result |
| --- | --- | --- |
| RT-01 The rule applies | An Architect rule sends work to `public` | The Architect's task goes to `public`, chosen by the persona rule; the answer is not cached. A Frontend task without a rule goes to the first allowed model. |
| RT-02 My switch wins | An Architect rule and an admin-changed Complex level | The rule decides without a switch; the developer's switch to `private` or `outside` wins over both. |
| RT-03 Rule beats level | Complex is changed to `outside`; a Frontend rule sends work to `private` | The level decides alone; with the rule, the rule decides. |
| RT-04 Level inside the project | No admin change, then an admin choice the project's class doesn't allow | Keeplane's picks by model ID; then Keeplane's pick among the project's models. |
| RT-05 Rule outside the project | The rule's model is approved only for Public | The level's model is used, and the answer never names the rule's model. |
| RT-06 Gateway-only or unusable | The rule's model definition changes outside Keeplane; a rule on `private` while the developer's key is missing | The task goes to another allowed model; with the key back, the rule applies. Removing a rule's model is refused. |
| RT-07 Switch outside the project | The developer switches to a model the project may not use, or to a gateway-only model | 403 “This model is not eligible for the project”; no persona rule replaces the switch. |
| RT-08 Switch without own key | The developer switched to `private` but their key is missing | The task goes to the Architect rule's model with reason “missing”; without a persona, to the first allowed model. |
| RT-09 Nothing allowed | The only model needs the developer's missing key | No model. |
| RT-10 Invalid requests | Unknown persona or level, an empty model, an unknown field, two personas | 400. |
| RT-11 Session, project, policy | Invalid session, policy outage, an unregistered or malformed project | 401, 503 “Model routing is unavailable”, 403, 403. |
| RT-12 Project refused | The deployment's access policy refuses the project for this developer | 403 with no model named. |
| RT-13 No secrets | Any answer | No key, fingerprint, session or key directory appears. |
| RT-14 Gateway still decides | The routed model is sent through the gateway entry check | It is admitted. |
