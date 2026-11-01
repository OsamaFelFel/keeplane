"""Fail when the component manifest no longer describes the files in this repo."""

import hashlib
import json
import re
import runpy
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/keeplane"
CONTROL_PLANE = ROOT / "components/control-plane"
ADMIN_UI = ROOT / "components/admin-ui"
MANIFEST = json.loads((ROOT / "deploy/component-manifest.json").read_text())
STAMP = runpy.run_path(str(ROOT / "deploy/stamp_component_manifest.py"))
UPDATE = (
    "Update deploy/component-manifest.json; see docs/architecture/component-manifest.md"
)


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def without_comment(line):
    return re.sub(r"(^|\s)#.*$", "", line).rstrip()


def yaml_scalars(text):
    """Map dotted keys to scalars for the plain block mappings used by the chart."""
    found, stack, skip_below = {}, [], None
    for raw in text.splitlines():
        line = without_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if skip_below is not None and indent > skip_below:
            continue
        skip_below = None
        while stack and stack[-1][0] >= indent:
            stack.pop()
        content = line.strip()
        if content.startswith("- "):
            skip_below = indent
            continue
        key, separator, value = content.partition(":")
        if not separator:
            continue
        path = ".".join([name for _, name in stack] + [key.strip()])
        if value.strip():
            found[path] = unquote(value)
        else:
            stack.append((indent, key.strip()))
    return found


def yaml_list(text, key):
    """Read a top-level list of flat mappings such as Chart.yaml dependencies."""
    items, inside = [], False
    for raw in text.splitlines():
        line = without_comment(raw)
        if not line.strip():
            continue
        if not line.startswith((" ", "-")):
            inside = line.startswith(key + ":")
            continue
        if not inside:
            continue
        content = line.strip()
        if content.startswith("- "):
            items.append({})
            content = content[2:]
        name, _, value = content.partition(":")
        items[-1][name.strip()] = unquote(value)
    return items


def requirement_pins(path):
    pins = {}
    for line in path.read_text().splitlines():
        match = re.match(r"([A-Za-z0-9_.\-]+)==([^\s;]+)", line.strip())
        if match:
            pins[match.group(1)] = match.group(2)
    return pins


CHART_META = yaml_scalars((CHART / "Chart.yaml").read_text())
VALUES = yaml_scalars((CHART / "values.yaml").read_text())
STACK_LOCK = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())


def test_chart_identity_matches_chart_yaml():
    """MANIFEST-01"""
    chart = MANIFEST["chart"]
    assert (chart["name"], chart["version"], chart["app_version"]) == (
        CHART_META["name"],
        CHART_META["version"],
        CHART_META["appVersion"],
    ), UPDATE
    assert (ROOT / chart["path"] / "Chart.yaml").is_file()
    assert STACK_LOCK["charts"]["keeplane"] == "keeplane-" + chart["version"], UPDATE


def test_gateway_dependency_matches_chart_lock_and_vendored_archive():
    """MANIFEST-02"""
    gateway = MANIFEST["gateway"]["chart"]
    declared = yaml_list((CHART / "Chart.yaml").read_text(), "dependencies")
    locked = yaml_list((CHART / "Chart.lock").read_text(), "dependencies")
    expected = {
        "name": gateway["name"],
        "version": gateway["version"],
        "repository": gateway["repository"],
    }
    assert [{k: d[k] for k in expected} for d in declared] == [expected], UPDATE
    assert locked == [expected], UPDATE
    lock_digest = yaml_scalars((CHART / "Chart.lock").read_text())["digest"]
    assert gateway["lock_digest"] == lock_digest, UPDATE

    archive = ROOT / gateway["archive"]
    assert (
        hashlib.sha256(archive.read_bytes()).hexdigest() == gateway["archive_sha256"]
    ), UPDATE
    with tarfile.open(archive) as bundle:
        inner = bundle.extractfile(gateway["name"] + "/Chart.yaml").read().decode()
    vendored = yaml_scalars(inner)
    assert (vendored["name"], vendored["version"]) == (
        gateway["name"],
        gateway["version"],
    )
    assert (
        vendored["appVersion"].removeprefix("v")
        == MANIFEST["gateway"]["runtime_version"]
    )
    assert (
        STACK_LOCK["charts"]["agentgateway"]
        == gateway["name"] + "-" + gateway["version"]
    )
    assert (
        STACK_LOCK["runtime"]["agentgateway"] == MANIFEST["gateway"]["runtime_version"]
    )


def test_gateway_image_digest_matches_chart_values():
    """MANIFEST-03"""
    image = MANIFEST["gateway"]["image"]
    assert re.fullmatch(r"[a-z0-9./\-]+@sha256:[0-9a-f]{64}", image)
    assert VALUES["agentgateway-standalone.image"] == image, UPDATE
    assert STACK_LOCK["images"]["agentgateway"] == image, UPDATE


def test_gateway_stays_marked_as_trial_until_selected():
    """MANIFEST-04"""
    gateway = MANIFEST["gateway"]
    existing = MANIFEST["existing_gateway"]
    assert gateway["status"] == "integration-trial"
    assert gateway["release_selected"] is False
    # Only tested pairings are supported; nothing is supported before selection.
    assert existing["supported_versions"] == []
    assert MANIFEST["database_schema"]["postgres_server"]["supported_versions"] == []


def test_existing_gateway_versions_match_the_tested_trial():
    """MANIFEST-05"""
    existing = MANIFEST["existing_gateway"]
    supplied = yaml_scalars(
        (ROOT / "deploy/local/supplied-gateway-values.yaml").read_text()
    )
    trial = yaml_scalars((ROOT / "deploy/local/existing-values.yaml").read_text())
    assert (
        existing["preflight_expected_version"] == VALUES["gateway.expectedVersion"]
    ), UPDATE
    assert trial["gateway.expectedVersion"] == VALUES["gateway.expectedVersion"], UPDATE
    assert [
        (t["product"], t["version"], t["image"]) for t in existing["tested_versions"]
    ] == [("agentgateway", trial["gateway.expectedVersion"], supplied["image"])], UPDATE


def test_app_image_is_recorded_as_unpinned_with_empty_build_fields():
    """MANIFEST-06"""
    app = MANIFEST["app_image"]
    build = MANIFEST["build"]
    assert app["default_reference"] == VALUES["app.image"], UPDATE
    assert MANIFEST["release_status"] == "pre-release"
    assert app["pinned"] is ("@sha256:" in VALUES["app.image"])
    for field in ("keeplane_commit", "app_image_digest", "chart_package_digest"):
        assert build[field] is None, "The committed manifest stays unstamped"

    dockerfile = (CONTROL_PLANE / "Dockerfile").read_text()
    bases = set(
        re.findall(r"^FROM (python@sha256:[0-9a-f]{64})", dockerfile, re.MULTILINE)
    )
    assert bases == {app["base_image"]}, UPDATE
    sources = json.loads((CONTROL_PLANE / "licenses/runtime-sources.json").read_text())
    assert "python@" + sources["base_image"] == app["base_image"], UPDATE
    assert sources["python"]["version"] == app["python"], UPDATE
    assert sources["alpine_release"] == app["alpine_release"], UPDATE


def test_control_plane_packages_match_requirements():
    """MANIFEST-07"""
    control = MANIFEST["components"]["control_plane"]
    pins = requirement_pins(CONTROL_PLANE / "requirements-account-api.txt")
    assert control["python_packages"] == pins, UPDATE
    assert STACK_LOCK["python_packages"] == pins, UPDATE

    optional = control["optional"]
    postgres = requirement_pins(CONTROL_PLANE / "requirements-postgres.txt")
    assert {"psycopg": optional["postgres"]["psycopg"]} == postgres, UPDATE
    libpq = set(
        re.findall(r"\blibpq=(\S+)", (CONTROL_PLANE / "Dockerfile").read_text())
    )
    assert libpq == {optional["postgres"]["libpq"]}, UPDATE
    sign_in = requirement_pins(CONTROL_PLANE / "requirements-cli-auth.txt")
    for name, version in optional["cli_sign_in"].items():
        assert sign_in[name] == version, UPDATE
    detection = (CONTROL_PLANE / "requirements-detection.txt").read_text()
    detection_pins = requirement_pins(CONTROL_PLANE / "requirements-detection.txt")
    for name, version in optional["personal_data_detection"].items():
        assert detection_pins.get(name) == version or (
            f"/{name}-{version}/" in detection
        ), UPDATE


def test_admin_ui_and_cli_versions_match_their_packages():
    """MANIFEST-08"""
    ui = MANIFEST["components"]["admin_ui"]
    package = json.loads((ADMIN_UI / "package.json").read_text())
    lock = json.loads((ADMIN_UI / "package-lock.json").read_text())
    assert ui["package_version"] == package["version"], UPDATE
    resolved = {
        name: lock["packages"]["node_modules/" + name]["version"]
        for name in package["dependencies"]
    }
    assert ui["runtime_dependencies"] == resolved, UPDATE

    cli = MANIFEST["components"]["cli"]
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert (
        re.search(r'^name = "([^"]+)"', pyproject, re.MULTILINE).group(1)
        == cli["package"]
    )
    assert (
        re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)
        == cli["version"]
    ), UPDATE
    adapter = (ROOT / "components/cli/opencode_adapter.py").read_text()
    runtime = re.search(r'^VERSION = "([^"]+)"', adapter, re.MULTILINE).group(1)
    assert cli["coding_runtime"]["version"] == runtime, UPDATE


def migration_heads():
    from django.db.migrations.loader import MigrationLoader

    graph = MigrationLoader(None, ignore_no_migrations=True).graph
    heads = {}
    for folder in sorted(CONTROL_PLANE.glob("*/migrations")):
        app = folder.parent.name
        leaves = graph.leaf_nodes(app)
        assert len(leaves) == 1, (app, leaves, "needs exactly one migration head")
        heads[app] = leaves[0][1]
    return heads


def test_migration_heads_match_each_django_app():
    """MANIFEST-09"""
    assert MANIFEST["database_schema"]["migration_heads"] == migration_heads(), UPDATE


def test_api_version_matches_declared_routes():
    """MANIFEST-10"""
    routes = "".join(p.read_text() for p in CONTROL_PLANE.glob("*/*urls.py"))
    versions = sorted(set(re.findall(r"[\"']\^?api/(v\d+)/", routes)))
    declared = MANIFEST["api"]["declared_version"]
    assert versions == ([] if declared is None else [declared]), UPDATE


# Each chart switch maps to the feature name used in the manifest.
CHART_SWITCHES = {
    "gateway.install": "managed_gateway",
    "app.cliSignIn.enabled": "cli_sign_in",
    "app.postgres.enabled": "postgres",
    "app.localTrial.enabled": "local_trial",
    "networkPolicy.gatewayIngressEnabled": "gateway_ingress_network_policy",
    "networkPolicy.appIngressEnabled": "app_ingress_network_policy",
    "networkPolicy.egressEnabled": "egress_network_policy",
    "ingress.enabled": "ingress",
}
# Sub-settings that apply only once their parent feature is turned on.
CHART_SUB_SETTINGS = {"app.postgres.migration.enabled"}


def test_default_features_match_chart_values_and_stored_defaults():
    """MANIFEST-11"""
    from audit.models import AuditOption
    from data_classes.models import Settings

    switches = {k for k in VALUES if re.search(r"(^|\.)(enabled|install)$|Enabled$", k)}
    assert switches == set(CHART_SWITCHES) | CHART_SUB_SETTINGS, (
        "A chart switch was added or removed. " + UPDATE
    )
    assert VALUES["gateway.mode"] == (
        "managed" if VALUES["gateway.install"] == "true" else "existing"
    )
    assert {VALUES[key] for key in CHART_SWITCHES} <= {"true", "false"}
    defaults = {
        feature: VALUES[key] == "true" for key, feature in CHART_SWITCHES.items()
    }
    defaults["data_classes"] = Settings._meta.get_field("classes_enabled").default
    defaults["personal_data_detection"] = Settings._meta.get_field(
        "detection_enabled"
    ).default
    defaults["optional_audit_kinds"] = AuditOption._meta.get_field("enabled").default

    features = MANIFEST["features"]
    assert features["on_by_default"] == sorted(f for f, on in defaults.items() if on), (
        UPDATE
    )
    assert features["off_by_default"] == sorted(
        f for f, on in defaults.items() if not on
    ), UPDATE


COMMIT = "a" * 40
IMAGE = "registry.example.test/keeplane@sha256:" + "b" * 64


def test_stamp_fills_build_fields_without_changing_the_committed_manifest(tmp_path):
    """MANIFEST-12"""
    original = json.dumps(MANIFEST, sort_keys=True)
    output = tmp_path / "manifest.json"
    assert (
        STAMP["main"](
            [
                "--commit",
                COMMIT,
                "--app-image",
                IMAGE,
                "--chart-digest",
                "sha256:" + "c" * 64,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    stamped = json.loads(output.read_text())
    assert stamped["build"]["keeplane_commit"] == COMMIT
    assert stamped["build"]["app_image_digest"] == IMAGE
    assert stamped["build"]["chart_package_digest"] == "sha256:" + "c" * 64
    # The digest lives only under build; app_image still describes the chart default.
    assert stamped["app_image"] == MANIFEST["app_image"]
    assert json.dumps(MANIFEST, sort_keys=True) == original
    assert {k: v for k, v in stamped.items() if k != "build"} == {
        k: v for k, v in MANIFEST.items() if k != "build"
    }


@pytest.mark.parametrize(
    "commit, image, chart",
    [
        ("abc123", IMAGE, None),
        (COMMIT, "keeplane-preview:local", None),
        (COMMIT, "registry.example.test/keeplane:0.1.0", None),
        (COMMIT, IMAGE, "0.1.0"),
    ],
)
def test_stamp_refuses_short_commits_tags_and_malformed_digests(commit, image, chart):
    """MANIFEST-13"""
    with pytest.raises(ValueError):
        STAMP["stamp"](MANIFEST, commit=commit, app_image=image, chart_digest=chart)


def test_stamp_refuses_to_overwrite_the_committed_manifest():
    """MANIFEST-13"""
    with pytest.raises(SystemExit):
        STAMP["main"](
            [
                "--commit",
                COMMIT,
                "--app-image",
                IMAGE,
                "--output",
                str(ROOT / "deploy/component-manifest.json"),
            ]
        )


def test_yaml_reader_keeps_list_entries_out_of_mapping_keys():
    """MANIFEST-14: the file reader used above does not misread chart values."""
    nested = 'a:\n  b: "1"  # note\n  ports:\n    - name: http\n      port: 4000\n  c: x\nd: y\n'
    assert yaml_scalars(nested) == {"a.b": "1", "a.c": "x", "d": "y"}
    top_level = "deps:\n- name: g\n  version: v1\ndigest: sha256:1\n"
    assert yaml_scalars(top_level) == {"digest": "sha256:1"}
    assert yaml_list(top_level, "deps") == [{"name": "g", "version": "v1"}]
