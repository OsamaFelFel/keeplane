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
| MANIFEST-07 | Compare control-plane packages with the requirement files and Dockerfile. | Core packages, optional PostgreSQL driver and libpq, the optional sign-in package and the optional detector match their pins, and the listed detection image targets are exactly the Dockerfile targets that carry the detector. |
| MANIFEST-08 | Compare admin UI and CLI versions with their package files. | The UI version and resolved runtime dependencies match the lock file; the CLI package version and coding runtime version match their sources. |
| MANIFEST-09 | Load the Django migration graph. | Each app has exactly one head, and it is the recorded one. |
| MANIFEST-10 | Search the URL files for a versioned API path. | None exists, matching the manifest's undeclared API version. |
| MANIFEST-11 | Compare default features with chart switches and stored defaults. | Every chart switch is listed, including the detection install setting (`app.personalDataDetection.enabled`, off); on and off defaults match the chart values, Data Classes and optional Audit kinds. |
| MANIFEST-12 | Stamp a build copy with a commit, app image digest and chart digest. | The copy has those values under `build` only. `app_image` still names the chart's default reference and its pinned flag, and the committed manifest stays unchanged. |
| MANIFEST-13 | Stamp with a short commit, a tag, a malformed digest, or over the committed file. | The stamp is refused. |
| MANIFEST-14 | Read sample chart YAML with the test's file reader. | List items do not become mapping keys, so the checks above read the right values. |

## Stamping a build

Run `.venv/bin/python -m pytest tests/integration/test_component_manifest_build.py`.
These checks use a stand-in Docker command and a small chart package, so they
need neither Docker nor Helm. MANIFEST-15 also packages the real chart when
Helm is found; without Helm that case is skipped with the reason. The `live`
MANIFEST-17 case builds a one-file image from scratch and needs Docker:
add `-m live` to run it.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| MANIFEST-15 | Stamp a copy from a built image tag and a packaged chart. | The copy records the commit, the image ID Docker reports for the tag and the SHA-256 of the chart package. The chart Helm packages from `deploy/helm/keeplane` is accepted. The committed manifest stays unchanged. |
| MANIFEST-16 | Stamp with a package of another chart name, version or appVersion, a missing package, or a file that is not a chart package. | The stamp is refused and names the problem. |
| MANIFEST-17 | Stamp from an image tag Docker does not have, from a Docker answer that is not an image ID, or without Docker. | The stamp is refused and no copy is written. With real Docker, the ID read matches `docker image inspect`. |
| MANIFEST-18 | Check a copy against the build that stamped it. | The check passes and prints the commit, image and chart digest. |
| MANIFEST-19 | Check the committed manifest, a copy for another commit, image or chart package, a copy missing the chart digest, a copy with an edited or added section, or a copy with an extra build field. | Each copy is refused with the reason. |
| MANIFEST-20 | Read the CI workflow's `component-manifest` job. | It runs unless a pull request is documentation-only, has read-only access, uses actions pinned by commit, builds the UI and image, packages the chart, records the checked-out commit, stamps and checks the copy, and uploads it. It never writes `deploy/component-manifest.json`, and the workflow cannot push. |
