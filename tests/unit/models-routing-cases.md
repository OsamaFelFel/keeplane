# Models and routing cases

**Edition:** Open Source. Spec 004 (models and routing), tasks 004-01 to 004-04.
This catalog holds the add and set-up cases that run without a gateway, and
the map from every Spec 004 scenario to the cases that prove it.

## Add and set up a model (unit)

Run `.venv/bin/python -m pytest tests/unit/test_models_routing.py`. The gateway
is an in-memory model store and the local runner a loopback HTTP server; no
Docker, gateway or provider is used.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| MRS-01 | With data classes on, add an OpenAI model with a shared key, approved for Public and Internal. | Keeplane asks the model through the gateway first, then saves it with the shared key and both classes, owned by Keeplane. The gateway holds its definition, pointing at the key file only. |
| MRS-02 | With data classes off, add a model, even with classes in the request. | It is saved with no class. |
| MRS-03 | Add a model while Keeplane uses the customer's gateway. | The definition is written to that gateway and the model is set up. |
| MRS-04 | Choose Find models for a local runner, then add its model approved for Internal. | The runner's model is listed with its active context; the model is added with no key, pointing at the runner, approved for Internal. No key file is written. |
| MRS-05 | Add a model when the runner doesn't answer, the provider doesn't answer (502, 503) or the provider refuses the key (401, 403). | 503 with “The runner at [address] didn't answer.”, “[Provider] didn't answer.” or “[Provider] refused the key.”, then “Nothing was saved.” Nothing is left in the gateway, the catalog or the key folder; a runner that doesn't answer gets nothing written to the gateway. |
| MRS-06 | Add a cloud model or a local model when the gateway refuses the write. | 503 with “The gateway didn't register it. Nothing was saved.”; nothing is saved. |
| MRS-07 | Add the same model from the same provider again under another name. | 409 with “[Model] from [Provider] is already added.”; the gateway, the first model's setup and the key folder are unchanged. |
| MRS-08 | Edit a shared-key model and leave Replace shared key empty. | Keeplane asks the model again, writes nothing to the gateway and keeps the same key file and key. |
| MRS-09 | With data classes off, set up a model added outside Keeplane with no key. | It is set up with no class and no key, still not owned by Keeplane; nothing is written to the gateway. |
| MRS-10 | Find models on a local runner and add one. | Keeplane only reads the runner's model list and its properties and asks one short question; it sends no settings, load, unload or restart request. |

The same add and set-up rules on every gateway copy are the
[gateway copy cases](gateway-copy-cases.md); the live versions are the
[cloud add](../e2e/cloud-add-cases.md) and [model add](../e2e/model-add-cases.md)
cases.

## Spec 004 scenarios (ST10–ST17, ST23–ST27)

Each scenario in Spec 004 and the cases that prove it. Each case is in its own
catalog:

- MRS above; MOD-UI, CL-UI and PR-UI the [React unit cases](ui/cases.md); MO-UI
  the [browser Models cases](../browser/models-cases.md).
- ML the [model listing cases](model-listing-cases.md), MR the
  [removal cases](model-removal-cases.md), GC the
  [gateway copy cases](gateway-copy-cases.md), PR the
  [persona rule unit cases](persona-rule-cases.md), CODE the
  [signed-in coding cases](cli-signed-in-coding-cases.md), KC the
  [CLI provider-key cases](cli-provider-key-command-cases.md) and RETRY the
  [managed runtime configuration cases](runtime-config-cases.md).
- CL and CL-INT the [complexity level cases](../integration/complexity-level-cases.md),
  PR-INT the [persona rule cases](../integration/persona-rule-cases.md), RT the
  [task routing cases](../integration/task-routing-cases.md), MC the
  [model choice cases](../integration/model-choice-cases.md), ALT the
  [alternatives cases](../integration/model-alternatives-cases.md), OUT the
  [outage cases](../integration/native-runtime-outage-cases.md), PROTO the
  [protocol cases](../integration/native-runtime-protocol-cases.md), CAT the
  [runtime catalog cases](../integration/runtime-catalog-cases.md), KL the
  [key list cases](../integration/runtime-key-list-cases.md), PK the
  [provider-key cases](../integration/runtime-provider-key-cases.md), KR the
  [key check cases](../integration/developer-key-recheck-cases.md), MP the
  [model policy cases](../integration/model-policy-cases.md), PMR the
  [personal model setup cases](../integration/personal-model-registration-cases.md),
  DK-COUNT the [key count cases](../integration/personal-key-count-cases.md) and
  MA the [model answer record cases](../integration/model-answer-record-cases.md).
- The live cases: MODEL the [approval cases](../e2e/model-approval-cases.md),
  EDIT the [edit cases](../e2e/model-edit-cases.md), REMOVE the
  [removal cases](../e2e/model-removal-cases.md), REPLACE the
  [replacement cases](../e2e/model-replacement-cases.md), CADD the
  [cloud add cases](../e2e/cloud-add-cases.md), EXIST the
  [customer-run gateway cases](../e2e/existing-gateway-cases.md), LEVEL-LIVE the
  [live level cases](../e2e/complexity-levels-cases.md) and RULE-LIVE the
  [live rule cases](../e2e/persona-rules-cases.md).

`tests/unit/test_routing_scenario_map.py` fails if a scenario is missing here,
or a case named here has no row in its own catalog or no test.

| Story | Scenario | Checked by |
| --- | --- | --- |
| ST10 | Add a cloud model | MRS-01, ML-01, CADD-02, CADD-03, CADD-06 |
| ST10 | Data classes are off | MO-UI-02 (no class asked), MRS-02, MP-01 (every project) |
| ST10 | The customer runs its own gateway | MRS-03, EXIST-03 |
| ST10 | Add a model from a local runner | MRS-04, ML-05 (listed as Local), MO-UI-02 |
| ST10 | The model doesn't answer | MRS-05, MOD-UI-02, MO-UI-03, MO-UI-06, CADD-05 |
| ST10 | The gateway doesn't register the model | MRS-06, MOD-UI-02 |
| ST10 | Each developer adds their own key | PMR-01, PMR-02, MO-UI-06, PK-02 (the developer's key, in the CLI) |
| ST10 | Already added | MRS-07, MOD-UI-03, CADD-04 |
| ST11 | A shared key | CADD-02, MA-06, MA-07 (tied to the developer) |
| ST11 | See my keys | KL-01, KL-02 |
| ST11 | Add my own key | KC-01, KC-02 (hidden prompt), PK-01, PK-02 (checked with the provider), MC-01 |
| ST11 | Never on the developer's machine | KC-01, KR-01 |
| ST11 | Replace or remove my key | PK-01, MC-03 |
| ST11 | A refused key | Not built yet: Keeplane doesn't see a refusal on its own. The owner kept it manual until Spec 009 (governance issue #63, question 4): after `keeplane keys check` the key shows as refused, KR-02. |
| ST11 | No key yet | MC-02, MC-06, MC-13 |
| ST12 | No models yet | CAT-01, CODE-01 |
| ST13 | Keeplane's picks | CL-INT-01, CL-UI-01, LEVEL-LIVE-01 |
| ST13 | How Keeplane picks | CL-03, CL-04, CL-05, CL-06, CL-07 |
| ST13 | Context window not known | CL-08 |
| ST13 | Change a pick | CL-INT-03, CL-UI-02, MO-UI-08, LEVEL-LIVE-02 |
| ST13 | Go back to Keeplane's pick | CL-INT-03, CL-UI-03, MO-UI-08 |
| ST14 | Route by complexity | Not built yet: judging a task's complexity waits for task 004-03's router choice (ADR 024, governance issue #44). |
| ST15 | Add a persona rule | PR-INT-01, PR-UI-02, MO-UI-10, RULE-LIVE-01 |
| ST15 | The rule applies | RT-01, PR-05, RT-14 |
| ST16 | A model is down | RETRY-01, OUT-01, OUT-02, OUT-03, OUT-07, OUT-10, CODE-03, ALT-01, ALT-02 |
| ST16 | The model answers on a retry | OUT-04, OUT-05, OUT-06 |
| ST16 | A task too big for the model | RETRY-02, OUT-08, CODE-05 |
| ST16 | Down, and no other model allowed | ALT-03, CODE-04 |
| ST16 | Too big, and no other model allowed | CODE-06 |
| ST17 | See the model | Not built yet: the CLI doesn't show which model answered. The Developer CLI waits for Spec 009 (governance issue #28). |
| ST17 | Switch the model | Not built yet: the CLI has no switch; `--model` names one task's model. It waits for Spec 009 (governance issue #28). |
| ST17 | My switch beats Keeplane's picks | RT-02, RT-07, PR-05; the server's routing order, which the CLI's switch will use |
| ST23 | Edit a model | EDIT-02, CADD-07, GC-14, MO-UI-05 |
| ST23 | Keep the shared key | MRS-08, CADD-07 |
| ST23 | Remove a model | MR-04, MR-06, REMOVE-03 |
| ST23 | A model in use | MR-20, MR-22, CL-INT-06, PR-INT-06, CL-UI-05, PR-UI-05, MO-UI-09, MO-UI-11, LEVEL-LIVE-03, RULE-LIVE-02 |
| ST23 | Keeplane's own pick | CL-INT-05 |
| ST23 | A model added outside Keeplane | MR-01, REMOVE-04, MO-UI-04, MC-16, EDIT-05 |
| ST24 | Listed but unused | ML-01, MP-02 (even with no class), MODEL-01, MODEL-02, REPLACE-01, EXIST-03 |
| ST24 | Set it up | MODEL-05, MODEL-06, MO-UI-05, GC-09 |
| ST24 | Set it up with data classes off | MRS-09, MP-01 |
| ST25 | Loading | MOD-UI-04 |
| ST25 | The gateway isn't answering | MOD-UI-05 |
| ST25 | No gateway name | MOD-UI-06 |
| ST26 | Request settings pass through | PROTO-01, CODE-02 |
| ST26 | The runner is left alone | MRS-10 |
| ST27 | Key count | DK-COUNT-01, DK-COUNT-02, DK-COUNT-03, MOD-UI-01 |

The table follows the owner's and associate product owner's decisions where
they are newer than the spec's wording: a down or too-big task is never
switched to another model (governance issues #37, #52 and #57), the three
levels and their picks (issues #39 and #50), and persona rules for the fixed
personas (keeplane #178). A change that adds or widens access waits for every
gateway copy (keeplane #179); those states are GC-10 to GC-25. Models and
routing's planned “not yet ready on [N] of [M] gateway copies” (keeplane #202
and #207) isn't a Spec 004 scenario yet and isn't built.
