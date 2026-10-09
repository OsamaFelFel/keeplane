# Recognize native cloud models in an existing gateway

These cases use the protected Docker preview and a local fixed-answer upstream.
They test how Keeplane handles models that an administrator added directly to
the gateway. They do not call a real cloud provider or store a provider key.

1. Register a native OpenAI model and a native Anthropic model directly in the
   gateway. Keeplane lists their provider names and Cloud reach, marks both
   "Added outside Keeplane", and gives neither an approved data class.
2. Ask for either model through Keeplane before setup. Both requests are refused
   and no answer is returned.
3. Set up the no-key OpenAI trial model with Public. Keeplane checks its answer
   through the gateway, lists it as approved with No key needed, and can use it.
4. Remove only these trial approvals and gateway resources. Existing models and
   the running previews remain available.

The [live verifier](test_cloud_listing.py) saves a dated JSON result in `runs/`.
Shared and personal provider keys need separate evidence before those modes
appear in the product UI.
