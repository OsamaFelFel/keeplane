# Try model approval during Add model

Start the [protected Docker preview](local-preview.md) or [managed kind preview](kubernetes-local.md). Sign in as `first-admin` at Models and routing on [port 3000](http://127.0.0.1:3000/) or [port 13000](http://127.0.0.1:13000/).

Choose **Add model**, enter `http://qwen:8080`, choose **Find models**, select `qwen2.5-coder:0.5b`, then choose **Add model**. If data classes are on, you may also select **Approved for** classes. Keeplane checks the runner and registered gateway route before saving setup. The model row shows any selected classes while the mode is on. If that model already appears in the list because of earlier preview tests, use its **Set up** action; Add model reports duplicates without changing them.

To remove a model added through Keeplane, choose **Edit**, then **Remove model**.
The confirmation tells you that Keeplane also removes its gateway registration.
For a model registered directly in the gateway, the action is **Remove Keeplane
setup** and leaves the gateway registration in place. The
[removal cases](../../tests/e2e/model-removal-cases.md) check both paths.

The [plain-English cases](../../tests/e2e/model-add-cases.md) and `python3 tests/e2e/test_model_add.py` test the same protected endpoint with a fresh fixture model, a separate alias of the real Qwen runner, empty or invalid class selections, duplicate registration, and an intentional no-answer rollback. The test removes its trial models afterward. Its [JSON run](../../tests/e2e/runs/2026-10-10-optional-data-classes-full-final.json) is versioned.

Both protected previews also let you select **OpenAI** or **Anthropic** in
Add model, enter a model ID and a shared provider key, and optionally approve data classes when the mode is on.
This currently exercises each provider's API format against a local
authenticated mock; it does **not** call a live provider. The route still goes
through agentgateway, and Keeplane checks one answer before saving approval.
The shared key is stored in a restricted file mounted read-only into the
gateway. Only a file reference is held in its model definition. **Each
developer's own key** is visible but disabled until the CLI flow is built.
The [cloud registration cases](../../tests/e2e/cloud-add-cases.md) and
`python3 tests/e2e/test_cloud_add.py` verify both provider formats, key
handling, rejection, class editing, and removal. In **Edit**, leave **Replace
shared key** empty to keep the key, or enter a new one. Keeplane validates a
replacement through a temporary gateway model before changing the approved
route. The [rotation cases](../../tests/e2e/key-rotation-cases.md) and
`python3 tests/e2e/test_key_rotation.py` check invalid, wrong, unchanged and
working replacements. The [cloud add run](../../tests/e2e/runs/2026-10-09-cloud-add.json)
and [key rotation run](../../tests/e2e/runs/2026-10-09-key-rotation.json)
are versioned.

A gateway write that cannot be verified may leave an unapproved model visible;
the error names that possibility so an admin can inspect it.
