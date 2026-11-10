"""Run the real shell launcher with isolated commands; never start a cluster."""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("missing", "node_version", "docker_ready", "message", "calls"),
    [
        ("custom-helm", "v22.12.0", True, "Missing tool: custom-helm", []),
        (None, "v22.11.0", True, "Node.js 22.12 or newer is required", ["node"]),
        (None, "invalid-version", True, "Node.js 22.12 or newer is required", ["node"]),
        (None, "v22.12.0", False, "Docker is unavailable", ["node", "docker"]),
        (None, "v24.0.0", True, "Missing models/", ["node", "docker"]),
    ],
    ids=["missing-helm", "old-node", "invalid-node", "stopped-docker", "prerequisites-pass"],
)
def test_kind_startup_checks_prerequisites_before_model_or_state_work(
    tmp_path, missing, node_version, docker_ready, message, calls
):
    root = tmp_path / "repo"
    launcher = root / "deploy/local/kind-up.sh"
    launcher.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "deploy/local/kind-up.sh"
    runtime = tmp_path / "runtime"
    launcher.write_text(source.read_text())
    commands = tmp_path / "bin"
    commands.mkdir()
    (commands / "dirname").symlink_to(shutil.which("dirname"))
    (commands / "python3").symlink_to(sys.executable)
    log = tmp_path / "commands.txt"
    for name in ("node", "npm", "docker", "kind", "kubectl", "custom-helm", "rg", "shasum", "openssl"):
        if name == missing:
            continue
        script = commands / name
        content = '#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(name) + ' >> "$KEEPLANE_CHECK_CALLS"\n'
        if name == "node":
            content += 'printf "%s\\n" ' + shlex.quote(node_version) + "\n"
        elif name == "docker" and docker_ready:
            content += "exit 0\n"
        else:
            content += "exit 1\n"
        script.write_text(content)
        script.chmod(0o755)
    result = subprocess.run(
        ["/bin/sh", str(launcher)],
        check=False, cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": str(commands), "KEEPLANE_HELM_BIN": "custom-helm",
             "KEEPLANE_CHECK_CALLS": str(log), "KEEPLANE_RUNTIME_DIR": str(runtime),
             "KEEPLANE_KUBECONFIG": str(tmp_path / "kubeconfig")},
    )
    assert result.returncode == 1
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    if message != "Missing models/":
        assert "Missing models/" not in result.stderr
    assert (log.read_text().splitlines() if log.exists() else []) == calls
    assert not runtime.exists()
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()) == [
        "deploy/local/kind-up.sh",
    ]


def run_launcher_without_qwen(tmp_path, qwen):
    """Pass the prerequisites with stubs; stop at the first dependency build."""
    root = tmp_path / "repo"
    launcher = root / "deploy/local/kind-up.sh"
    launcher.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "deploy/local/kind-up.sh"
    launcher.write_text(source.read_text())
    commands = tmp_path / "bin"
    commands.mkdir()
    for tool in ("dirname", "mkdir", "chmod"):
        (commands / tool).symlink_to(shutil.which(tool))
    (commands / "python3").symlink_to(sys.executable)
    log = tmp_path / "commands.txt"
    for name in ("node", "npm", "docker", "kind", "kubectl", "helm", "shasum", "openssl"):
        content = '#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(name) + ' >> "$KEEPLANE_CHECK_CALLS"\n'
        content += {"node": 'printf "v22.12.0\\n"\n', "docker": "exit 0\n"}.get(name, "exit 1\n")
        (commands / name).write_text(content)
        (commands / name).chmod(0o755)
    runtime = tmp_path / "runtime"
    result = subprocess.run(
        ["/bin/sh", str(launcher)],
        check=False, cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": str(commands), "KEEPLANE_CHECK_CALLS": str(log),
             "KEEPLANE_RUNTIME_DIR": str(runtime), "KEEPLANE_KIND_QWEN": qwen,
             "KEEPLANE_KUBECONFIG": str(tmp_path / "kubeconfig")},
    )
    return result, runtime, log


def test_kind_startup_without_qwen_skips_the_model_file_and_uses_the_runtime_folder(tmp_path):
    result, runtime, log = run_launcher_without_qwen(tmp_path, "off")
    assert result.returncode != 0
    assert "Missing models/" not in result.stderr
    assert "Traceback" not in result.stderr
    # Credentials go to KEEPLANE_RUNTIME_DIR, then setup stops at the UI build.
    assert (runtime / "first-admin-password").is_file()
    assert oct(runtime.stat().st_mode & 0o777) == "0o700"
    assert log.read_text().splitlines() == ["node", "docker"]
    assert not (tmp_path / "kubeconfig").exists()


def test_kind_startup_refuses_an_unknown_qwen_setting_before_state_work(tmp_path):
    result, runtime, _ = run_launcher_without_qwen(tmp_path, "maybe")
    assert result.returncode == 1
    assert "KEEPLANE_KIND_QWEN must be on or off." in result.stderr
    assert not runtime.exists()
