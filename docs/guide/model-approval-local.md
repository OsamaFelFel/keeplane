# Try model approval in the local account preview

Start the [protected account preview](accounts-local.md), then open
[Models and routing](http://127.0.0.1:3000/). A model already present in the
gateway appears as **Added outside Keeplane** with **Not set · gets no work**.
Choose **Set up**, select its approved data classes, and save. Keeplane checks
that the model answers before it records approval. The local trial supports
no-key models and Keeplane-managed shared keys for cloud-format models against
a local authenticated fixture. Developer-owned keys remain future work.
The class choices come from the [Data classes page](data-classes-local.md),
where admins can add or rename classes and change their approved models.
The model list identifies native OpenAI and Anthropic gateway models as Cloud
and marks them unapproved until Keeplane setup. The
[native-provider cases](../../tests/e2e/cloud-listing-cases.md) use a local mock
to verify that outside models receive no work before setup and that a no-key
OpenAI trial can answer after approval. They do not test a real cloud account.
An approved outside model has **Edit** in the Models table. Editing its
approved classes checks that it still answers before saving. **Remove
Keeplane setup** stops work through the protected Keeplane API but leaves the
model registered in the customer gateway. The confirmation dialog states this
effect.

A model added through Keeplane shows **Remove model** in its Edit dialog. That
action removes its gateway registration and Keeplane approval. If someone has
changed the gateway definition since Keeplane added it, removal is refused to
protect the changed model. An admin can set up that definition again; Keeplane
then treats it as an outside model and **Remove Keeplane setup** preserves it.
Approvals saved before this ownership distinction also count as outside models.

The protected preview stores approvals in a Docker volume, so restarting its app
does not erase them. Approval is bound to the gateway model definition as well
as its name. If the definition changes, Keeplane stops using it until an admin
sets it up again. Removing an approval through the trial API leaves the model
in the gateway. Only work sent through the protected Keeplane API is subject to
this gate. The separate kind preview remains an integration trial and has not
yet been given the Open Source account boundary.

Run the [plain-English cases](../../tests/e2e/model-approval-cases.md) and the
recorded checks:

```sh
python3 tests/e2e/test_local.py
python3 tests/e2e/test_model_approval.py
python3 tests/e2e/test_model_edit.py
python3 tests/e2e/test_model_replacement.py
python3 tests/e2e/test_model_removal.py
python3 tests/e2e/test_cloud_listing.py
python3 tests/e2e/test_model_catalog.py
python3 tests/e2e/test_accounts.py
```

The model approval test removes its trial approval at the end. Its
[observations](../../tests/e2e/runs/2026-10-09-model-approval.json) cover the
before, approved, restarted and removed states. Production needs a shared
catalog database, authenticated developer traffic, class-aware routing and a
gateway artifact that passes the release gates.
The [live replacement cases](../../tests/e2e/model-replacement-cases.md) create
a separate disposable gateway model, change its upstream definition under the
same name, and verify that Keeplane blocks it until a new approval. The runner
deletes its own gateway resource afterward.
The [model removal cases](../../tests/e2e/model-removal-cases.md) check both
removal paths and the changed-definition refusal; the
[recorded run](../../tests/e2e/runs/2026-10-09-model-removal.md) includes the
full local regression. Removal of models referenced by future routing rules
still needs a separate guard when those rules exist.
