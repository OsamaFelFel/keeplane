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

This checks one fixed chat route and selected native model backends on the pinned
gateway. It does not prove production publication, routing/fallback coverage,
provider-key isolation, TLS, Kubernetes network policy or replica behavior.
