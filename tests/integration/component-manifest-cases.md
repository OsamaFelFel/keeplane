# Component manifest cases

Run `.venv/bin/python -m pytest tests/integration/test_component_manifest.py`
from the repository root. The checks read files only; they need no Docker,
Helm or Kubernetes. They prove that
[`deploy/component-manifest.json`](../../deploy/component-manifest.json) still
describes the repository. They do not prove that the recorded set has passed
the full regression; each regression run reports that separately.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| MANIFEST-01 | Compare the chart entry with `Chart.yaml` and the local stack lock. | Name, version and appVersion match. |
| MANIFEST-02 | Compare the gateway chart with `Chart.yaml`, `Chart.lock` and the vendored archive. | Name, version, repository and lock digest match; the archive has the recorded SHA-256 and its own chart metadata gives the same version. |
| MANIFEST-03 | Compare the gateway image with chart values and the local stack lock. | All three use the same `@sha256:` reference. |
| MANIFEST-04 | Read the gateway and support entries. | The gateway stays an integration trial, not a release choice. No customer-run gateway or PostgreSQL server version is listed as supported. |
| MANIFEST-05 | Compare the tested customer-run gateway with the trial values. | Its version equals the preflight expected version in both value files, and its image equals the separately installed gateway's image. |
| MANIFEST-06 | Read the app image and build fields. | The image is the chart's default tag and is marked unpinned. Commit and digest fields stay empty in Git. Base image, Python and Alpine match the Dockerfile and recorded runtime sources. |
| MANIFEST-07 | Compare control-plane packages with the requirement files and Dockerfile. | Core packages, optional PostgreSQL driver and libpq, and the optional sign-in package match their pins. |
| MANIFEST-08 | Compare admin UI and CLI versions with their package files. | The UI version and resolved runtime dependencies match the lock file; the CLI package version and coding runtime version match their sources. |
| MANIFEST-09 | Load the Django migration graph. | Each app has exactly one head, and it is the recorded one. |
| MANIFEST-10 | Search the URL files for a versioned API path. | None exists, matching the manifest's undeclared API version. |
| MANIFEST-11 | Compare default features with chart switches and stored defaults. | Every chart switch is listed; on and off defaults match the chart values, Data Classes and optional Audit kinds. |
| MANIFEST-12 | Stamp a build copy with a commit, app image digest and chart digest. | The copy has those values under `build` only. `app_image` still names the chart's default reference and its pinned flag, and the committed manifest stays unchanged. |
| MANIFEST-13 | Stamp with a short commit, a tag, a malformed digest, or over the committed file. | The stamp is refused. |
| MANIFEST-14 | Read sample chart YAML with the test's file reader. | List items do not become mapping keys, so the checks above read the right values. |
