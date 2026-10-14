# Add and manage models

Start Keeplane using the [local setup guide](local-preview.md), open the printed
address and choose **Models and routing**. Add, Set up, Edit and Remove work;
complexity and persona routing are still being built.

Choose **Add model**, enter `http://qwen:8080`, choose **Find models**, select `qwen2.5-coder:0.5b`, then choose **Add model**. If data classes are on, you may also select **Approved for** classes. Keeplane checks the runner and registered gateway route before saving setup. The model row shows any selected classes while the mode is on. If that model already appears in the list because of earlier preview tests, use its **Set up** action; Add model reports duplicates without changing them.

To remove a model added through Keeplane, choose **Edit**, then **Remove model**.
The confirmation tells you that Keeplane also removes its gateway registration.
For a model registered directly in the gateway, the action is **Remove Keeplane
setup** and leaves the gateway registration in place. The
[removal cases](../../tests/e2e/model-removal-cases.md) check both paths.

The [plain-English cases](../../tests/e2e/model-add-cases.md) and `python3 tests/e2e/test_model_add.py` test the same protected endpoint with a fresh fixture model, a separate alias of the real Qwen runner, empty or invalid class selections, duplicate registration, and an intentional no-answer rollback. The test removes its trial models afterward. Its [JSON run](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-10-optional-data-classes-full-final.json) is versioned.

Both managed protected previews also let you select **OpenAI** or **Anthropic** in
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
working replacements. The [cloud add run](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-09-cloud-add.json)
and [key rotation run](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-09-key-rotation.json)
are versioned.

The separate customer-run gateway trial supports no-key models but rejects a
shared cloud key before saving it, because the customer-run gateway cannot
read Keeplane's provider-key volume. The error stays in the Add dialog. See
the [gateway mode guide](gateway-configuration.md) for the remaining key-delivery
requirement.

A gateway write that cannot be verified may leave an unapproved model visible;
the error names that possibility so an admin can inspect it.

## Registration and request settings

Keeplane registers models through the gateway's management API, confirms the
stored definition and checks an answer through the gateway before reporting
success. Customer-managed runners keep their own configuration.

Active context is the limit configured for the running model. Training-context
metadata is informational. Changing the gateway registration does not increase
a runner's allocated context. The [local guide](local-preview.md#model-limits)
shows how to configure the bundled demo runner.

Temperature and output limits are request parameters. The planned client passes
those through the gateway; Add model does not edit or restart a customer's runner.
