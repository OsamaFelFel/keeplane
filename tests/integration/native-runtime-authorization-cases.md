# Native gateway policy callback

Run `python -m pytest -q -m live tests/integration/test_native_runtime_authorization.py`.
Docker must have the locked gateway/Python images and a built application image
cached. `KEEPLANE_RUNTIME_FIXTURE_IMAGE` can name that application image; by default
the test uses the local preview image. It mounts the current Django source and
uses a disposable database, synthetic credentials and a mock provider only.

- A sibling client holds only its developer session and requested project ID. The native gateway injects its separate private credential and sends only UUID/model metadata to the real Django callback.
- After the selected-model check, native header removal keeps the developer credential and Keeplane context headers away from the keyless mock provider; the fixture records presence flags only.
- An allowed class/model reaches the mock once. Public, outside, unknown-project and revoked-session requests do not reach it.
- A deliberate rewrite after entry authorization selects Public. A second native check identifies Public and denies it, rather than reusing the earlier Private decision.
- Unknown protected routes do not expose management. A sibling cannot connect to the raw model, admin, stats, readiness, authorizer or provider listeners.
- Approval withdrawal and authorizer outage fail closed, with no additional mock calls.
- The existing configuration keeps its unrelated file-owned model intact and listed, but that model receives no protected work without Keeplane setup.
- Both disposable modes remove their containers and internal network, including on failure. No host ports, external inference or shared previews are used.

The same cases also run with a synthetic shared provider key. Native backend
authentication replaces the developer credential only after selected-model
authorization; the mock requires its exact expected key. Evidence stores only
whether that key matched and whether client/session/context headers leaked.
Removing the active managed key, making it unreadable, withdrawing approval or
revoking the account stops provider contact, including when native configuration
retains a loaded key after reload fails.

A separate bounded diagnostic first edits a valid key file in place, then publishes
a different key through a new native model revision/file reference and reads the
revision back. Neither step deletes a file. Up to three provider probes per stage
record new-key match booleans and statuses under `KEEPLANE_TEST_REPORT_DIR`; stale
or refused results are retained even when the authorization cases pass. Deletion
is tested afterward. This diagnostic does not establish safe rotation across
replicas or customer key delivery. Existing-mode tests use an explicit synthetic
file mount; Keeplane's unsupported customer shared-key API still returns 422.

This checks one fixed chat route and selected native model backends on the pinned
gateway. It does not prove production publication, routing/fallback coverage,
provider-key isolation, TLS, Kubernetes network policy or replica behavior.
