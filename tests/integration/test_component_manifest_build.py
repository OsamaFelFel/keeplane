"""Stamp the component manifest from a built image and chart, and check the copy."""

import hashlib
import io
import json
import re
import runpy
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.support.helm import HelmNotFound, resolve_helm

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "deploy/component-manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text())
STAMP = runpy.run_path(str(ROOT / "deploy/stamp_component_manifest.py"))
WORKFLOW = (ROOT / ".github/workflows/checks.yml").read_text()

COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
OTHER_ID = "sha256:" + "d" * 64


def chart_package(path, *, name=None, version=None, app_version=None):
    """Write a minimal chart package the way helm package lays it out."""
    chart = MANIFEST["chart"]
    name = name or chart["name"]
    text = (
        "apiVersion: v2\n"
        f"name: {name}\n"
        f"version: {version or chart['version']}\n"
        f'appVersion: "{app_version or chart["app_version"]}"\n'
    ).encode()
    with tarfile.open(path, "w:gz") as bundle:
        info = tarfile.TarInfo(name + "/Chart.yaml")
        info.size = len(text)
        bundle.addfile(info, io.BytesIO(text))
    return path


def fake_docker(tmp_path, *, output, code=0, error=""):
    script = tmp_path / "docker"
    script.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' '{output}'\n"
        f"printf '%s\\n' '{error}' >&2\n"
        f"exit {code}\n"
    )
    script.chmod(0o755)
    return str(script)


def run(*args):
    return STAMP["main"]([str(arg) for arg in args])


def stamped_copy(tmp_path, package, docker):
    output = tmp_path / "component-manifest.json"
    assert (
        run(
            "--commit",
            COMMIT,
            "--app-image-from-docker",
            "keeplane-preview:local",
            "--docker",
            docker,
            "--chart-package",
            package,
            "--output",
            output,
        )
        == 0
    )
    return output


def test_stamp_records_the_built_image_id_and_chart_package_digest(tmp_path):
    """MANIFEST-15"""
    package = chart_package(tmp_path / "keeplane-0.1.0.tgz")
    docker = fake_docker(tmp_path, output=IMAGE_ID)
    output = stamped_copy(tmp_path, package, docker)

    build = json.loads(output.read_text())["build"]
    assert build["keeplane_commit"] == COMMIT
    assert build["app_image_digest"] == IMAGE_ID
    assert build["chart_package_digest"] == (
        "sha256:" + hashlib.sha256(package.read_bytes()).hexdigest()
    )
    assert json.loads(MANIFEST_PATH.read_text()) == MANIFEST


def test_stamp_from_a_real_helm_package(tmp_path):
    """MANIFEST-15: the chart helm actually packages is the one the manifest names."""
    try:
        helm = resolve_helm()
    except HelmNotFound as error:
        pytest.skip(str(error))
    result = subprocess.run(
        (helm, "package", ROOT / MANIFEST["chart"]["path"], "--destination", tmp_path),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    package = tmp_path / "{name}-{version}.tgz".format(**MANIFEST["chart"])
    digest = STAMP["chart_package_digest"](package, MANIFEST)
    assert digest == "sha256:" + hashlib.sha256(package.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "fields",
    [{"version": "9.9.9"}, {"name": "other-chart"}, {"app_version": "0.2.0"}],
)
def test_stamp_refuses_a_package_of_another_chart_or_version(tmp_path, fields):
    """MANIFEST-16"""
    package = chart_package(tmp_path / "chart.tgz", **fields)
    with pytest.raises(ValueError, match="manifest records|not a packaged"):
        STAMP["chart_package_digest"](package, MANIFEST)


def test_stamp_refuses_a_missing_or_unreadable_package(tmp_path):
    """MANIFEST-16"""
    with pytest.raises(ValueError, match="No chart package"):
        STAMP["chart_package_digest"](tmp_path / "missing.tgz", MANIFEST)
    broken = tmp_path / "broken.tgz"
    broken.write_text("not a chart")
    with pytest.raises(ValueError, match="not a packaged"):
        STAMP["chart_package_digest"](broken, MANIFEST)


@pytest.mark.parametrize(
    "output, code, error",
    [
        ("", 1, "Error: No such image: keeplane-preview:local"),
        ("keeplane-preview:local", 0, ""),
        ("sha256:abc", 0, ""),
    ],
)
def test_stamp_refuses_an_image_docker_cannot_identify(tmp_path, output, code, error):
    """MANIFEST-17"""
    docker = fake_docker(tmp_path, output=output, code=code, error=error)
    with pytest.raises(ValueError, match="no built image"):
        STAMP["local_image_id"]("keeplane-preview:local", docker)
    with pytest.raises(SystemExit):
        run(
            "--commit",
            COMMIT,
            "--app-image-from-docker",
            "keeplane-preview:local",
            "--docker",
            docker,
            "--output",
            tmp_path / "out.json",
        )
    assert not (tmp_path / "out.json").exists()


def test_stamp_refuses_when_docker_is_missing(tmp_path):
    """MANIFEST-17"""
    with pytest.raises(ValueError, match="Could not run"):
        STAMP["local_image_id"]("keeplane-preview:local", str(tmp_path / "none"))


@pytest.mark.live
def test_local_image_id_reads_a_real_docker_image(tmp_path):
    """MANIFEST-17: live; builds a one-file image from scratch, no registry needed."""
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker is not installed")
    (tmp_path / "marker").write_text("component manifest check\n")
    (tmp_path / "Dockerfile").write_text("FROM scratch\nCOPY marker /marker\n")
    tag = "keeplane-manifest-check:" + tmp_path.name.lower()[-20:].strip("-_.")
    built = subprocess.run(
        (docker, "build", "-q", "-t", tag, tmp_path),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert built.returncode == 0, built.stderr
    try:
        expected = subprocess.run(
            (docker, "image", "inspect", "--format", "{{.Id}}", tag),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.strip()
        assert STAMP["local_image_id"](tag, docker) == expected
    finally:
        subprocess.run(
            (docker, "image", "rm", tag), check=False, capture_output=True, timeout=60
        )


def test_check_accepts_the_copy_this_build_stamped(tmp_path, capsys):
    """MANIFEST-18"""
    package = chart_package(tmp_path / "keeplane-0.1.0.tgz")
    docker = fake_docker(tmp_path, output=IMAGE_ID)
    output = stamped_copy(tmp_path, package, docker)
    assert (
        run(
            "--commit",
            COMMIT,
            "--app-image-from-docker",
            "keeplane-preview:local",
            "--docker",
            docker,
            "--chart-package",
            package,
            "--check",
            output,
        )
        == 0
    )
    assert "matches commit " + COMMIT in capsys.readouterr().out


def edited(stamped, change):
    copy = json.loads(json.dumps(stamped))
    change(copy)
    return copy


STAMPED = STAMP["stamp"](
    MANIFEST, commit=COMMIT, app_image=IMAGE_ID, chart_digest="sha256:" + "c" * 64
)
EXPECTED = {
    "commit": COMMIT,
    "app_image": IMAGE_ID,
    "chart_digest": "sha256:" + "c" * 64,
}


@pytest.mark.parametrize(
    "copy, expected, reason",
    [
        (MANIFEST, EXPECTED, "is not stamped"),
        (STAMPED, {**EXPECTED, "commit": "e" * 40}, "keeplane_commit"),
        (STAMPED, {**EXPECTED, "app_image": OTHER_ID}, "app_image_digest"),
        (STAMPED, {**EXPECTED, "chart_digest": OTHER_ID}, "chart_package_digest"),
        (
            edited(STAMPED, lambda m: m["build"].update(chart_package_digest=None)),
            EXPECTED,
            "chart_package_digest is not stamped",
        ),
        (
            edited(STAMPED, lambda m: m["gateway"].update(release_selected=True)),
            EXPECTED,
            "differ from the committed manifest: gateway",
        ),
        (
            edited(STAMPED, lambda m: m.update(supported_release="0.1.0")),
            EXPECTED,
            "supported_release",
        ),
        (
            edited(STAMPED, lambda m: m["build"].update(signed_by="someone")),
            EXPECTED,
            "fields the committed manifest does not",
        ),
    ],
    ids=[
        "unstamped",
        "other-commit",
        "other-image",
        "other-chart",
        "chart-missing",
        "edited-section",
        "added-section",
        "extra-build-field",
    ],
)
def test_check_refuses_an_unstamped_mismatched_or_edited_copy(copy, expected, reason):
    """MANIFEST-19"""
    with pytest.raises(ValueError, match=re.escape(reason)):
        STAMP["check"](copy, MANIFEST, **expected)


def test_check_refuses_the_committed_manifest_from_the_command_line(tmp_path):
    """MANIFEST-19"""
    with pytest.raises(SystemExit):
        run(
            "--commit",
            COMMIT,
            "--app-image",
            IMAGE_ID,
            "--check",
            MANIFEST_PATH,
        )
    (tmp_path / "list.json").write_text("[]")
    with pytest.raises(SystemExit):
        run(
            "--commit",
            COMMIT,
            "--app-image",
            IMAGE_ID,
            "--check",
            tmp_path / "list.json",
        )


def workflow_job(name):
    match = re.search(
        r"^  " + re.escape(name) + r":\n(.*?)(?=^  \S|\Z)",
        WORKFLOW,
        re.MULTILINE | re.DOTALL,
    )
    assert match, name + " job is missing from checks.yml"
    return match.group(1)


def test_ci_build_job_stamps_checks_and_uploads_the_copy():
    """MANIFEST-20"""
    job = workflow_job("component-manifest")
    assert job.startswith(
        "    needs: scope\n"
        "    if: ${{ !cancelled() && (needs.scope.result != 'success' || "
        "needs.scope.outputs.docs_only != 'true') }}\n"
    )
    assert "    permissions:\n      contents: read\n" in job
    for action in re.findall(r"uses: (\S+)", job):
        assert re.fullmatch(r"[\w.\-/]+@[0-9a-f]{40}", action), action
    for step in (
        "npm run build",
        "docker build",
        'HELM_BIN" package deploy/helm/keeplane',
        "--app-image-from-docker keeplane-preview:local",
        "--chart-package",
        '--output "$out/component-manifest.json"',
        '--check "$out/component-manifest.json"',
        "actions/upload-artifact@",
    ):
        assert step in job, step
    assert "git rev-parse HEAD" in job
    # The stamped copy is a build result, never written back to the repository.
    assert "deploy/component-manifest.json" not in job
    assert "contents: write" not in WORKFLOW
    assert "git push" not in WORKFLOW and "git commit" not in WORKFLOW
