# Try model approval in the local account preview

Start the [protected Docker preview](accounts-local.md) or [managed kind preview](kubernetes-local.md), then open Models and routing on [port 3000](http://127.0.0.1:3000/) or [port 13000](http://127.0.0.1:13000/). A model already present in the
gateway appears as **Added outside Keeplane** with **Not set · gets no work**.
Choose **Set up** and save. If data classes are on, you can select its approved
classes; when they are off, there is no class field. Keeplane checks
that the model answers before it records approval. The local trial supports
no-key models and Keeplane-managed shared keys for cloud-format models against
a local authenticated fixture. [Personal setup](personal-model-setup.md) is
available for fixed cloud models; its installed coding path remains open.
The class choices come from the [Data classes page](data-classes-local.md),
where admins can add or rename classes and change their approved models.
The model list identifies native OpenAI and Anthropic gateway models as Cloud
and marks them unapproved until Keeplane setup. The
[native-provider cases](../../tests/e2e/cloud-listing-cases.md) use a local mock
to verify that outside models receive no work before setup and that a no-key
OpenAI trial can answer after approval. They do not test a real cloud account.
An approved outside model has **Edit** in the Models table. Editing its
approved classes while the mode is on checks that it still answers before saving. **Remove
Keeplane setup** stops work through the protected Keeplane API but leaves the
model registered in the customer gateway. The confirmation dialog states this
effect.

A model added through Keeplane shows **Remove model** in its Edit dialog. That
action removes its gateway registration and Keeplane approval. If someone has
changed the gateway definition since Keeplane added it, removal is refused to
protect the changed model. An admin can set up that definition again; Keeplane
then treats it as an outside model and **Remove Keeplane setup** preserves it.
Approvals saved before this ownership distinction also count as outside models.

If the gateway refuses the deletion, Keeplane keeps the model and shows the
gateway's error. If Keeplane can't save the removal, the model stays in the
gateway; when the database fails only after the gateway deleted it, Keeplane
puts the same definition back and says so. For a model where developers use
their own provider keys, they must check those keys again afterwards. If the
write back fails, the message asks you to check Models. Neither failure writes
a settings-change record. One case is not caught: if the gateway deletes the
model but its answer is lost, for example to a timeout, Keeplane keeps the
approval while the model is gone from the gateway. Models no longer lists the
model and it receives no work; the leftover approval matches no gateway
definition and is replaced if a model with that name is set up again.

The Docker preview stores approvals in a Docker volume, and the managed kind
preview uses its own PersistentVolumeClaim. Restarting either app does not erase
its approvals. Approval is bound to the gateway model definition as well
as its name. If the definition changes, Keeplane stops using it until an admin
sets it up again. Removing an approval through the trial API leaves the model
in the gateway. Only work sent through the protected Keeplane API is subject to
this gate. The managed kind preview has the same local account boundary; the
customer-supplied gateway fixture remains a separate, unprotected trial.

Run the [plain-English cases](../../tests/e2e/model-approval-cases.md) and the
recorded checks:

```sh
.venv/bin/python -m pytest tests/e2e/test_local.py -m live
.venv/bin/python -m pytest tests/e2e/test_model_approval.py -m live
.venv/bin/python -m pytest tests/e2e/test_model_edit.py -m live
.venv/bin/python -m pytest tests/e2e/test_model_replacement.py -m live
.venv/bin/python -m pytest tests/e2e/test_model_removal.py -m live
.venv/bin/python -m pytest tests/e2e/test_cloud_listing.py -m live
.venv/bin/python -m pytest tests/integration/test_model_catalog.py
.venv/bin/python -m pytest tests/e2e/test_accounts.py -m live
```

The model approval test removes its trial approval at the end. Its
[observations](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-09-model-approval.json) cover the
before, approved, restarted and removed states. Production needs a shared
catalog database, authenticated developer traffic, class-aware routing and a
gateway artifact that passes the release gates.
The [live replacement cases](../../tests/e2e/model-replacement-cases.md) create
a separate disposable gateway model, change its upstream definition under the
same name, and verify that Keeplane blocks it until a new approval. The runner
deletes its own gateway resource afterward.
The [model removal cases](../../tests/e2e/model-removal-cases.md) check both
removal paths and the changed-definition refusal; the
[recorded run](https://github.com/OsamaFelFel/keeplane/blob/6cf7bfc2a3defce262a2da1fe526a2d37fe33cc6/tests/e2e/runs/2026-10-09-model-removal.md) includes the
full local regression. A model an admin chose for a
[complexity level](complexity-levels.md) is kept, and removal lists the levels
that use it; a model that is only Keeplane's pick can be removed. Persona rules
are not built yet, so they need the same guard when they exist.
