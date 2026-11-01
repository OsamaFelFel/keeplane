"""Render the chart with and without the personal-data detection install setting.

Cases CD-01 to CD-07 in chart-detection-cases.md. CD-01 to CD-05 render the
chart with Helm and are skipped when Helm is missing; CD-06 and CD-07 read the
values file and the guides and always run.
"""

import difflib
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "deploy/helm/keeplane/values.yaml"
REFERENCE = ROOT / "docs/guide/kubernetes-installation-reference.md"
DATA_CLASSES = ROOT / "docs/guide/data-classes-local.md"
SETTING = "KEEPLANE_PERSONAL_DATA_DETECTION"
LOCAL_EXISTING = ("-f", "deploy/local/existing-values.yaml")


@pytest.fixture(scope="module")
def chart():
    """Rendered chart helpers; skips without Helm, as the other chart checks do."""
    from tests.integration import test_chart_installation_shape as shape

    return shape


def render(chart, tmp_path, values, *args):
    path = tmp_path / f"values-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps(values))
    return chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                     "-f", str(path), *args)


def existing(chart, detection=True, resources=None):
    values = chart.postgres_values("existing")
    values["app"]["personalDataDetection"] = {"enabled": detection}
    if resources is not None:
        values["app"]["resources"] = resources
    return values


def app_container(chart, output):
    app = next(doc for doc in chart.of_kind(output, "Deployment")
               if chart.name_of(doc) == "keeplane-app")
    return app, next(item for item in chart.containers(app)
                     if chart.scalar(item, "name") == "app")


def probe_path(chart, container, probe):
    return chart.scalar("\n".join(chart.block(container, probe)), "path")


def rendered(result):
    assert result.returncode == 0, result.stderr
    return result.stdout


def changes(before, after):
    """The lines removed from and added to a rendering, stripped."""
    diff = list(difflib.ndiff(before.splitlines(), after.splitlines()))
    return ([line[2:].strip() for line in diff if line.startswith("- ")],
            [line[2:].strip() for line in diff if line.startswith("+ ")])


def test_cd_01_off_by_default_nothing_changes(chart, tmp_path):
    (tmp_path / "m.json").write_text(json.dumps(chart.postgres_values("managed")))
    (tmp_path / "e.json").write_text(json.dumps(chart.postgres_values("existing")))
    for label, args in {
        "postgres-managed": ("-f", str(tmp_path / "m.json")),
        "postgres-existing": ("-f", str(tmp_path / "e.json")),
        "local-managed": ("-f", "deploy/local/values.yaml"),
        "local-existing": LOCAL_EXISTING,
    }.items():
        output = rendered(chart.run("template", "keeplane", chart.CHART,
                                    "--namespace", "keeplane", *args))
        assert SETTING not in output, label
        _, container = app_container(chart, output)
        expected = "/health/ready" if label.startswith("postgres") else "/health/app"
        assert probe_path(chart, container, "readinessProbe") == expected, label


def test_cd_02_enabled_sets_only_the_install_setting(chart, tmp_path):
    before = rendered(render(chart, tmp_path, existing(chart, detection=False)))
    after = rendered(render(chart, tmp_path, existing(chart)))
    _, container = app_container(chart, after)
    assert (SETTING, "1", False) in chart.env(container)
    # The setting goes to the app only: no Job, gateway or preflight gets it.
    assert after.count(SETTING) == 1
    # Every other line of every rendered object is unchanged, so every
    # security default stays: user, read-only root, capabilities, Secret
    # modes, service account token, network policies, images. No init
    # container, volume or download step is added: the model is in the image.
    assert changes(before, after) == ([], [f"- name: {SETTING}", 'value: "1"'])


def test_cd_03_readiness_waits_for_the_model_and_liveness_does_not(chart, tmp_path):
    local = tmp_path / "local.json"
    local.write_text(json.dumps({"app": {"personalDataDetection": {"enabled": True}}}))
    before = rendered(chart.run("template", "keeplane", chart.CHART,
                                "--namespace", "keeplane", *LOCAL_EXISTING))
    after = rendered(chart.run("template", "keeplane", chart.CHART,
                               "--namespace", "keeplane", *LOCAL_EXISTING, "-f", str(local)))
    # The SQLite local trial switches readiness to /health/ready, which also
    # waits for the model's first load; nothing else changes.
    assert changes(before, after) == (
        ["path: /health/app"],
        [f"- name: {SETTING}", 'value: "1"', "path: /health/ready"],
    )
    for output in (rendered(render(chart, tmp_path, existing(chart))), after):
        app, container = app_container(chart, output)
        assert probe_path(chart, container, "readinessProbe") == "/health/ready"
        assert probe_path(chart, container, "livenessProbe") == "/health/app"
        assert chart.scalar(container, "readOnlyRootFilesystem") == "true"
        assert chart.scalar(container, "runAsUser") == "65532"
        assert chart.scalar(app, "automountServiceAccountToken") == "false"


@pytest.mark.parametrize("limit", ["1Gi", "1024Mi", "1536Mi", "2Gi", "1.5Gi",
                                   "1073741824", 1073741824, "1100M", "2G"])
def test_cd_04_a_memory_limit_of_at_least_1gi_is_accepted(chart, tmp_path, limit):
    values = existing(chart, resources={"requests": {"memory": "1Gi"},
                                        "limits": {"memory": limit}})
    _, container = app_container(chart, rendered(render(chart, tmp_path, values)))
    assert "memory:" in "\n".join(chart.block(container, "resources"))


@pytest.mark.parametrize("limit", ["512Mi", "1023Mi", "1G", "1000M", "0.5Gi",
                                   "1073741823", 536870912, "900Mi"])
def test_cd_04_a_memory_limit_below_1gi_is_refused(chart, tmp_path, limit):
    result = render(chart, tmp_path, existing(chart, resources={"limits": {"memory": limit}}))
    assert result.returncode != 0
    assert "app.personalDataDetection needs app.resources.limits.memory of at least 1Gi" \
        in result.stderr
    # The same limit without detection is the installer's own choice.
    off = existing(chart, detection=False, resources={"limits": {"memory": limit}})
    assert render(chart, tmp_path, off).returncode == 0


@pytest.mark.parametrize("limit", ["lots", "1 Gi", "1gi", "1e9", "-1Gi"])
def test_cd_04_an_unreadable_memory_limit_is_refused(chart, tmp_path, limit):
    result = render(chart, tmp_path, existing(chart, resources={"limits": {"memory": limit}}))
    assert result.returncode != 0
    assert "app.resources.limits.memory: write the memory" in result.stderr


def test_cd_05_the_managed_gateway_is_refused(chart, tmp_path):
    values = chart.postgres_values("managed")
    values["app"]["personalDataDetection"] = {"enabled": True}
    result = render(chart, tmp_path, values)
    assert result.returncode != 0
    assert "app.personalDataDetection requires gateway.mode=existing" in result.stderr
    local = tmp_path / "local.json"
    local.write_text(json.dumps({"app": {"personalDataDetection": {"enabled": True}}}))
    result = chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                       "-f", "deploy/local/values.yaml", "-f", str(local))
    assert result.returncode != 0
    assert "managed gateway in this chart doesn't run Keeplane's checks" in result.stderr
    # Text instead of a true/false value is refused by the values schema.
    values = existing(chart)
    values["app"]["personalDataDetection"] = {"enabled": "yes"}
    assert render(chart, tmp_path, values).returncode != 0
    values["app"]["personalDataDetection"] = {"enabled": True, "model": "other"}
    assert render(chart, tmp_path, values).returncode != 0


def test_cd_06_values_file_keeps_detection_off_and_explains_it():
    text = VALUES.read_text()
    block = text.split("  personalDataDetection:\n", 1)[1].split("\n  runnerUrls:", 1)[0]
    assert re.search(r"^    enabled: false$", block, re.M)
    for words in ("KEEPLANE_PERSONAL_DATA_DETECTION=1", "postgres-detection",
                  "1Gi", "gateway.mode=existing", "offline"):
        assert words in block, words


def test_cd_07_guides_tell_the_installer_what_detection_needs():
    reference = REFERENCE.read_text()
    section = reference.split("## Personal-data detection\n", 1)[1].split("\n## ", 1)[0]
    for words in (
        "app.personalDataDetection.enabled", "postgres-detection",
        "postgres-cli-auth-detection", "KEEPLANE_PERSONAL_DATA_DETECTION",
        "1Gi", "1536Mi", "/health/ready", "readOnlyRootFilesystem",
        "No download", "gateway.mode=existing", "isn't installed",
        "network policies",
    ):
        assert words in section, words
    guide = DATA_CLASSES.read_text()
    assert "kubernetes-installation-reference.md#personal-data-detection" in guide
    assert "postgres-detection" in guide
