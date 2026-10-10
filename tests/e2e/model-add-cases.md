# Add a local model with data-class approval

These cases cover the protected Docker preview against its real agentgateway and deterministic local model fixture. The same registration contract will be rerun when the gateway component changes. The local runner UI uses the same protected registration endpoint after checking that its model answers.

1. **Choose classes while adding.** Open Add model as an admin. When data classes are on, the dialog lists them; when off, it hides those fields. A served model can be added with no class approval.
2. **Keep setup independent of classes.** Submit a new fixture model without approved classes. It is set up with an empty approval list. A request naming a class that does not exist is rejected before registration.
3. **Register and approve in one request.** Submit a new fixture model with Public and Internal. Keeplane reads the gateway registration back, gets a model answer through the gateway, saves the approved classes, and shows the model ready for work.
4. **Use only approved classes.** The protected model list and data-class lists show the chosen classes. A developer request to the model through Keeplane succeeds.
5. **Keep duplicate behavior.** Repeating the same model registration reports that it already exists and preserves its approval and gateway definition.
6. **Use the real local runner.** Register a separate alias of the running Qwen model with Public approval. The runner and gateway must both return a real answer, and the model must be listed as approved.
7. **Roll back a model that does not answer through the gateway.** The test fixture intentionally returns HTTP 503 for one reserved upstream model ID. Keeplane reports failure, removes the new gateway registration, and does not approve the model.
8. **Clean up only the trial models.** Remove their Keeplane approvals and gateway registrations. Other model definitions and both local previews remain available.

The test does not prove cloud-provider keys, two-replica atomicity, or model classification. A gateway accepted write followed by a failed readback/inference triggers a guarded cleanup attempt; if cleanup cannot be verified, the API reports that the model may remain unapproved instead of claiming nothing was saved.
