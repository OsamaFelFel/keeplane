# Component manifest

[`deploy/component-manifest.json`](../../deploy/component-manifest.json) names
the components this repository builds and tests together: the Keeplane chart,
the app image, the gateway chart and image, package versions, database
migrations, default features and the customer-run gateway versions tested.
Release checks, install reviews and other builds can read it instead of
collecting versions from many files.

Keeplane has not been released. The manifest describes the current
pre-release set; it supports nothing yet.

```mermaid
flowchart LR
  Sources[Chart.yaml, Chart.lock, values.yaml,<br/>Dockerfile, requirements, package files,<br/>migrations] --> Check[Manifest check<br/>tests/integration]
  Manifest[deploy/component-manifest.json<br/>build fields empty] --> Check
  subgraph CI[CI job component-manifest in checks.yml]
    UI[npm run build<br/>admin UI] --> Image[docker build<br/>keeplane-preview:local]
    Chart[helm package<br/>keeplane chart .tgz]
    Commit[Checked-out commit]
    Image -->|image ID| Stamp[stamp_component_manifest.py<br/>--output]
    Chart -->|SHA-256| Stamp
    Commit --> Stamp
    Stamp --> Verify[stamp_component_manifest.py<br/>--check]
  end
  Manifest --> Stamp
  Manifest --> Verify
  Verify --> Artifact[Workflow artifact<br/>component-manifest-commit:<br/>stamped copy and chart package]
  Verify --> Summary[Run summary:<br/>commit and digests]
```

The stamped copy is a build result. It is never committed.

## What it records

| Section | Contents |
| --- | --- |
| `build` | Keeplane commit, app image digest and chart package digest. Empty in Git; see below. |
| `chart` | Keeplane chart name, version and appVersion. |
| `app_image` | The chart's default app image, whether it is pinned, and its Python base image. |
| `gateway` | The gateway chart dependency, its archive hash and the image digest the chart uses. |
| `components` | Control-plane Python packages and optional extras, admin UI runtime dependencies, CLI package and coding runtime. |
| `api` | The declared HTTP API version. The `/api/...` paths have none yet. |
| `database_schema` | The latest migration for each Django app, and the PostgreSQL server versions supported. |
| `features` | Features on and off in a default chart install. |
| `existing_gateway` | Customer-run gateway versions supported and tested, and the version the preflight expects. |
| `upgrade_paths` | Tested upgrades. None until a version ships. |

### Current limits

- The gateway entry is the agentgateway **integration trial**
  (`"release_selected": false`). The release gateway has not been chosen.
- The app image is a local preview tag (`keeplane-preview:local`) and is marked
  `"pinned": false`. No registry image is published.
- Customer-run gateway support is empty. Agentgateway 1.6.0 has run only as a
  separately installed gateway in the local kind trial. The preflight accepts
  that one exact version.
- No PostgreSQL server version is declared supported. Tests use the fixture
  image in `deploy/local/stack.lock.json`.

`deploy/local/stack.lock.json` pins the local test environment (kind node, test
model, fixture images). The manifest describes what Keeplane installs. The
check makes sure the two agree where they overlap.

## Update it

Change the manifest in the same commit as the change it describes: chart or
dependency version, gateway image, Python or UI package, migration, chart
switch or tested gateway version. Then run:

```sh
.venv/bin/python -m pytest tests/integration/test_component_manifest.py
```

A failure names the check that no longer matches. Fix the manifest entry, or
the source file if the manifest was right. To get the gateway archive hash, run
`sha256sum deploy/helm/keeplane/charts/<archive>.tgz`.

Do not add a version to `supported_versions` until the full regression has
passed with it. The check refuses any supported gateway version while the
gateway entry is still a trial.

## Build-time fields

The commit, app image digest and chart package digest exist only after a build.
They stay `null` in Git. A build writes a filled copy and keeps it with its
results.

### In CI

The `component-manifest` job in
[`.github/workflows/checks.yml`](../../.github/workflows/checks.yml) runs on
pushes to `main`, manual runs and pull requests. Documentation-only pull
requests skip it, like the other application jobs. The job has read-only
repository access. It:

1. builds the admin UI, then the app image from
   `components/control-plane/Dockerfile`, tagged `keeplane-preview:local` (the
   chart's default reference);
2. packages `deploy/helm/keeplane` with the pinned Helm 3.19.0;
3. stamps the manifest with the checked-out commit, the image ID Docker reports
   and the SHA-256 of the chart package;
4. runs the script again with `--check`, which looks the values up again and
   refuses the copy unless they match and every other section equals the
   committed manifest;
5. uploads the copy and the chart package as the `component-manifest-<commit>`
   artifact, kept for 30 days, and writes the three values to the run summary.

On a pull request, the checked-out commit is GitHub's test merge commit, so
that commit is recorded. No image is pushed to a registry, so
`app_image_digest` holds the local image ID (`sha256:<digest>`). It identifies
the image built in that run but cannot be pulled. A registry build would record
`repository@sha256:<digest>` instead. The stamped copy names the component set
one run built and tested; it does not make that set a release.

The [install guide](../guide/kubernetes-local.md#know-which-component-set-you-install)
shows readers how to find and check the copy for a commit.

### By hand

```sh
python3 deploy/stamp_component_manifest.py \
  --commit "$(git rev-parse HEAD)" \
  --app-image-from-docker keeplane-preview:local \
  --chart-package test-results/keeplane-0.1.0.tgz \
  --output test-results/component-manifest.json
python3 deploy/stamp_component_manifest.py \
  --commit "$(git rev-parse HEAD)" \
  --app-image-from-docker keeplane-preview:local \
  --chart-package test-results/keeplane-0.1.0.tgz \
  --check test-results/component-manifest.json
```

`--app-image registry.example.test/keeplane@sha256:<digest>` or
`--app-image sha256:<image-id>` can replace `--app-image-from-docker`.
`--chart-digest sha256:<digest>` can replace `--chart-package`; the chart is
optional until it is published as a package.

The script accepts only a full 40-character commit and digests, not tags. It
refuses a chart package whose name, version or appVersion differ from the
manifest, and it will not overwrite the committed manifest. It changes only the
`build` section; `app_image` keeps describing the chart's default reference, so
a stamped copy can still show `"pinned": false` for that default.

## What the check covers

[`tests/integration/test_component_manifest.py`](../../tests/integration/test_component_manifest.py)
reads the repository files directly; it needs no Docker, Helm or cluster.
[`tests/integration/test_component_manifest_build.py`](../../tests/integration/test_component_manifest_build.py)
covers stamping and checking with a stand-in Docker command and chart package.
It uses real Helm when available; one `live` case needs Docker.
The [cases](../../tests/integration/component-manifest-cases.md) list each
check. In short, it fails when:

- the chart name, version or appVersion, gateway dependency, `Chart.lock`
  digest, vendored archive or gateway image digest changes;
- the base image, Python version, pinned Python packages, optional PostgreSQL
  or sign-in packages, admin UI dependencies or CLI versions change;
- a Django app gets a new migration or more than one head;
- a versioned API path appears or a chart switch is added, removed or changes
  default;
- a gateway or PostgreSQL version is listed as supported before release, or
  build fields are committed filled in;
- a stamped copy is unstamped, belongs to another commit, image or chart
  package, or differs from the committed manifest outside `build`;
- the CI job stops building, stamping, checking or uploading the copy, or gains
  write access.

The check proves the manifest matches the source files. It does not prove the
component set works; the [regression suite](../guide/regression-local.md) does
that.
